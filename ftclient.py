import argparse
import fileinput
from pathlib import Path
#import glob
import hashlib
import math
import os
import random
import socket
import signal
import sys
import threading
import time
import traceback

debug = False

# 0 = Nothing set
# 1 = Connected to server
# 2 = Waiting for receive
# 3 = Sending
mode = 0 

MAIN_SERVER = ""
RECV_ID = 0
clients = [] # Holds all the client objects
senderIdAndFile = {} # key = senderId, value = (filename, start time, printed transfer complete, printed start clock)
global_lock = threading.Lock()

def calculateMd5(filename):
    hash_md5 = hashlib.md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def writeToFile(firstOffset, senderId, offset, data):
    filename = str(firstOffset) + "." + str(senderId)
    
    if not os.path.exists("tmp"):
        os.makedirs("tmp")
    
    if "DATAFINISHED" in data:
        data = data.replace("DATAFINISHED", "")
        
    try:
        with open("tmp/" + filename, "r+") as file:
            file.seek(offset - firstOffset)
            file.write(data)
    except Exception as e:
        with open("tmp/" + filename, "w+") as file:
            file.write(data)
    
def combineAllFilesWith(senderId):
    while global_lock.locked():
        continue
    
    global_lock.acquire()
    
    main_file = None
    if not os.path.isfile(senderIdAndFile.get(senderId)[0]):
        main_file = open(senderIdAndFile.get(senderId)[0], "w+")
        main_file.close()
    main_file = open(senderIdAndFile.get(senderId)[0], "r+")
    
    if os.listdir("tmp"):
        print("Cleaning up. Please wait...")
    
    files = os.listdir("tmp")
    
    for file in files:
        if file.endswith("." + str(senderId)):
            try:
                main_file.seek(int(file.split(".")[0])) # Get the offset of the file
                main_file.writelines(fileinput.input("tmp/" + file))
            except Exception as e:
                print(e)
            finally:
                os.remove("tmp/" + file)
        if file == files[-1]:
            print("Done!")
    
    main_file.close()
    global_lock.release()

def removeClient(client):
    for c in clients:
        if c == client:
            clients.remove(c)
            break

def disconnectAllClients():
    for c in clients:
        removeClient(c)
        closeConnection(c)

def closeConnection(client):
    """End the connection to the client"""
    try:
        client.shutdown(socket.SHUT_RDWR)
        client.close()
    except Exception as e:
        if debug:
            print("Client appears to have already been disconnected.")
    finally:
        sys.exit()

def connectToServer(host, id, mode, buff_size, custom_recv_port):
    """Connect to the main server indicating which mode the client is in."""
    MAIN_SERVER = host
    host = host.split(":")
    RECV_ID = id
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host[0], int(host[1])))
        if mode == "SEND":
            s.send(("S " + str(id)).encode())
        elif mode == "RECEIVE":
            s.send(("R " + str(custom_recv_port)).encode())
        elif mode == "DONE":
            s.send(("D" + str(id)).encode())

        response = s.recv(buff_size)
        return response.decode("UTF-8"), s # REMOVED STRIP
    except ConnectionResetError:
        print("The server has disconnected. Press Ctrl-C to quit the client.")
        sys.exit()
    except Exception as e:
        print("An error occured while attempting to connect to the server. Please try again.")
        if debug:
            print(e)
        sys.exit()
    
def setupServer(port):
    """Set up a connection for the receiving server"""
    SERVER_RECV_ADDR = ('0.0.0.0', port)
    if debug:
        print("Server address is " + str(SERVER_RECV_ADDR))
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    connection.bind(SERVER_RECV_ADDR)
    connection.listen(10)

    return connection

def getFilename(path):
    """Returns the filename of a given path"""
    temp = path.split("/")
    return temp[-1]
    
def createHeader(offset, senderId):
    """Create a header for each line"""
    header = str(senderId) + ";"
    header += str(offset) + ";"
    return header.encode()

def parseHeader(data):
    """Parse the data provided by header and the data following it"""
    data = data.split(";", 2)
    if "DATAFINISHED" in data[0]:
        return 0, 0, "DATAFINISHED"
    senderId = ""
    offset = ""
    remaining_data = ""
    try:
        senderId = data[0]
        offset = data[1]
        remaining_data = data[2]
    except IndexError:
        print("An error occured with IndexError. Here is the data: ")
        print(data)
    
    
    return int(senderId), int(offset), remaining_data

def sendFile(response, filename, senderId, offset, finish_offset, buff_size):
    """Send the file to remote client"""

    try:
        host, port = response.split(":")
        if debug:
            print("Host: " + host + ". Port: " + str(port))
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(10)
        s.connect((host, int(port)))
        
        with open(filename, 'rb') as f:
            while offset < finish_offset:
                f.seek(offset, 0)
                header = createHeader(offset, senderId)
                offset += buff_size - len(header)
                thingToSend = header + f.read(buff_size - len(header))
                if offset >= finish_offset:
                    thingToSend += "DATAFINISHED".encode()
                s.send(thingToSend)
                #if debug:
                #    print("SENDING")
                #    print(thingToSend)
            
        #s.send("DATAFINISHED".encode())
        print("Transfer complete!")
        s.close()
    except ConnectionResetError:
        print("The other client has requested to terminate the connection.")
        print("Therefore, the file transfer process has been cancelled.")
        sys.exit()
    except socket.timeout:
        print("The connection has been lost. Please try again.")
        sys.exit()
    except FileNotFoundError:
        print("An error occured while opening the file. Ensure it exists and you have permission to read it.")
        sys.exit()
    except socket.error as e:
        print("The other client has terminated the file transfer.")
        if debug:
            print(e)
        sys.exit()
    except Exception as e:
        print("An unknown error has occured. Please try again.")
        print(e)
        sys.exit()

def createThreads(numThreads, response, filename, buff_size):
    increment = math.ceil((os.path.getsize(filename))/numThreads)
    if debug:
        print("The chunk of the file allocated to each thread is: " + str(increment) + " bytes")
        
    offset = 0
    finish_offset = increment
    senderId = random.randint(0, 13337)
    
    test_file = Path(filename)
    if not test_file.is_file():
        print("File '" + filename + "' does not exist.")
        sys.exit()
    try:
        host, port = response.split(":")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect((host, int(port)))
        initial_connection = "BUFFSIZE;" + str(buff_size) + ";FILENAME;"+ getFilename(filename) +";SENDERID;" + str(senderId) + ";NUMTHREADS;" + str(numThreads) + ";"
        s.send(initial_connection.encode())
        initial_response = s.recv(buff_size).decode("UTF-8")
        if "NAHFAMDISBUFFERTOOBIG" in initial_response:
            initial_response = initial_response.split(";")
            print("The receive client's buffer size is smaller than this client's.")
            print("Therefore, this client's buffer size has been changed to " + initial_response[2] + ".")
            buff_size = int(initial_response[2])
        elif "AIIGHTFAMITSALLGUCCI" in initial_response and debug:
            print("Buffer size all good on both ends.")
        elif "FILEALREADYEXISTS" in initial_response:
            print("The file already exists on the sender side. Cancelling transfer...")
            exit(0)
        else:
            if debug:
                print("Something went wrong with figuring out buffer size.")
    except Exception as e:
        if debug:
            print(e)
    finally:
        s.close()
    
    for x in range(numThreads):
        t = threading.Thread(target = sendFile, args =(response, filename, senderId, offset, finish_offset, buff_size))
        t.start()
        offset = finish_offset
        finish_offset += increment
    
def sendMode(host, id, filename, buff_size, numThreads):
    """Set the client to send mode and query the server for IP"""
    print("Asking '" + host + " about '" + id + "'...")
    response, s = connectToServer(host, id, "SEND", buff_size, 0)
    if debug:
        print("Response is: " + str(response))

    if response == "NOTFOUND":
        print("The client " + str(id) + " does not exist. Please try again.")
        s.close()
        exit(0)
    else:
        response = response.replace("(", "").replace("'", "").replace(")", "").replace(", ", ":").replace("ping", "")
        print("Found client at '" + response + "'...")
        print("Sending '" + filename + "'...")
        s.close()
        currentMode = 3
        
        # Do a for loop for numThreads init'ing a new thread each time
        # Each thread will then call sendFile (maybe add another argument for which 
        # fragment it's supposed to send)
        createThreads(numThreads, response, filename, buff_size)

def getRemoteFile(client, address, buff_size):
    """Setup the server and receive the file from the other client"""
    clients.append(client)
    data = client.recv(buff_size).decode("UTF-8") # REMOVED STRIP
    num_conn = 1
    if data == "SERVERISDISCONNECTING":
        print("The server has disconnected due to a shutdown. Please press Ctrl-C to quit the client.")
        closeConnection(client)
        removeClient(client)
    if "BUFFSIZE;" in data:
        data = data.split(";")
        if debug:
            print("Buffer size received from send client:" + data[1])
        if Path(data[3]).is_file(): # Check if file exists
            print(data[3] + " already exists. Cancelling transfer.")
            client.send("FILEALREADYEXISTS".encode())
            sys.exit()
        elif int(data[1]) > buff_size:
            return_data = "NAHFAMDISBUFFERTOOBIG;PLSUSE;" + str(buff_size) + ";"
            client.send(return_data.encode())
        else:
            client.send("AIIGHTFAMITSALLGUCCI".encode())
        senderIdAndFile.update({int(data[5]): (data[3], 0, False, False)})
        if debug:
            print("All elements in the sender/file:")
            print(str(senderIdAndFile))
        num_conn = data[7]
        if debug:
            print("Number of connections: " + str(num_conn))
        print("Receiving '" + str(data[3]) + "' over " + str(num_conn) + " connections at time ", end='')
        closeConnection(client)
        removeClient(client)
        sys.exit()

    senderId, offset, remaining = parseHeader(data)
    senderData = senderIdAndFile.get(senderId)
    filename = senderData[0]
    
    my_first_offset = offset
    
    writeToFile(my_first_offset, senderId, offset, remaining)
    finished = False
    numEmptyData = 0
    if senderData[1] == 0 and senderData[3] == False: # No start time is set
        senderData = (senderData[0], time.time(), False, True)
        senderIdAndFile.update({senderId: senderData})
        print(str(senderData[1]) + "...")
    while not finished:
        try:
            data = client.recv(buff_size).decode("UTF-8")
            if data == "":
                numEmptyData += 1
                continue
            else:
                numEmptyData = 0
            if numEmptyData > 29000:
                print("The other client has disconnected.")
                sys.exit()
            temp_senderId, temp_offset, data = parseHeader(data)
            if temp_senderId != 0:
                senderId = temp_senderId
            if temp_offset != 0:
                offset = temp_offset
            if "DATAFINISHED" in data:
                data = data.replace("DATAFINISHED", "")
                finished = True
            #file_obj.write(data)
            writeToFile(my_first_offset, senderId, offset, data)
        except socket.error:
            print("Disconnected from the other client(s).")
            sys.exit()
        except Exception as e:
            print("An unknown error has occured.")

    finish_time = time.time()
    if not senderIdAndFile.get(senderId)[2]:
        temp = (senderIdAndFile.get(senderId)[0], senderIdAndFile.get(senderId)[1], True, True)
        senderIdAndFile.update({senderId: temp})
        print("Transfer completed at time " + str(finish_time) + " in " + 
              str(finish_time - senderData[1]) + " seconds!")
    client.shutdown(socket.SHUT_RDWR)
    client.close()
    combineAllFilesWith(senderId)
    sys.exit()

def receiveMode(host, custom_recv_port, buff_size):
    """Handle receiving files from other clients"""
    print("Asking '" + host + "' about an identification number...")
    response, s = connectToServer(host, id, "RECEIVE", buff_size, custom_recv_port)
    currentMode = 2
    if debug:
        print("Response is: " + str(response))
    response = response.replace("ping", "")
    print("Issued '" + response + "' for identification...")
    connection = setupServer(custom_recv_port)
    while True:
        client, address = connection.accept()
        t = threading.Thread(target=getRemoteFile, args=(client,address, buff_size))
        t.start()  

def initiateExit(a, b):
    """Handles the force shut down from Control-C"""
    try:
        if currentMode == 0:
            print()
        elif currentMode == 1 or currentMode == 3:
            print("Disconnecting...")
            disconnectAllClients()
        elif currentMode == 2:
            print("Closing receiving")
    except Exception as e:
        if debug:
            print("An error occured while closing the program")
            print(e)
    finally:
        sys.exit()

parser = argparse.ArgumentParser(description = "Enter required arguments")
parser.add_argument("--server", help="Host address", nargs=1)
parser.add_argument("--receive", help="Set client to receive mode", action="store_true")
parser.add_argument("--send", help="Set client to send mode", nargs=2)
parser.add_argument("--debug", help="Debug information", action="store_true")
parser.add_argument("--port", "-p", help="Set the port for the receive client")
parser.add_argument("--size","-s", help="Set the receive buffer size")
parser.add_argument("--cons", "-c", help="Set number of connections")
args = parser.parse_args()

# Catch SIGINT (Control-C)
signal.signal(signal.SIGINT, initiateExit)

if args.debug:
    debug = True
    print("Hostname: " + socket.gethostname())
    print("Deleting big.txt if it exists...")
    if os.path.isfile("big.txt"):
        os.remove("big.txt")

if args.send and args.receive:
    print("The client cannot be set in both send and receive mode")
    exit(1)

if socket.gethostname() == "nike.cs.uga.edu" and args.receive:
    print()
    print("--------------------------------------------------------------------------------")
    print("| WARNING: Nike has some firewalls which prevent the server from communicating |")
    print("| with the client properly. This may cause issues when the server attempts     |")
    print("| to issue a shutdown signal to the client in receive mode or if a remote      |")
    print("| client (not running on Nike) wishes to communicate with this client.         |")
    print("|                                                                              |")
    print("| It is recommended to run the server and clients in various clusters to allow |")
    print("| cross communication, although running the client from Nike will work.        |")
    print("--------------------------------------------------------------------------------")
    print()

if args.send:
    if args.port:
        print("You cannot set a custom port on a client in send mode.")
        exit(2)
    currentMode = 1
    buff_size = 4096
    numThreads = 1
    if args.size:
        buff_size = args.size
    if args.cons:
        numThreads = args.cons
    if debug:
        print("Initiating sending mode")
        print("Server: " + str(args.server))
        print("ID: " + args.send[0])
        print("File: " + args.send[1])
        print("Buffer size: " + str(buff_size))
        print("Number of threads: " + str(numThreads))
    sendMode(str(args.server[0]), args.send[0], args.send[1], int(buff_size), int(numThreads))
elif args.receive:
    if args.cons:
        print("You cannot set the number of concurrent connections on a client in receive mode.")
        exit(3)
    if debug:
        print("Initiating receiving mode")
        print("Server: " + str(args.server[0]))
    currentMode = 1
    port = 47683
    buff_size = 4096
    if args.port:
        port = int(args.port)
    if args.size:
        buff_size = int(args.size)
    print("Buffer size set to " + str(buff_size) + "!")
    print("Using port " + str(port) + "!")
    receiveMode(args.server[0], port, int(buff_size))
