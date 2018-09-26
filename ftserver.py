import argparse
import os
import random
import signal
import socket
import sys
import threading

SERVER_PORT = 47682
SERVER_HOST = '0.0.0.0'
clients = [] # Clients format: (client, address, id, mode)
debug = False

def removeClient(client):
    """Removes a specified client from the clients list"""
    for c,a,i,m in clients:
        if c == client:
            clients.remove((c,a,i,m))
            return True
    return False

def closeConnection(client):
    """End the connection to the client"""
    if not removeClient(client) and debug:
        print("The specified client was not in the client list.")
    try:
        client.shutdown(socket.SHUT_RDWR)
        client.close()
    except Exception as e:
        if debug:
            print("Client may have already been disconnected.")
    finally:
        sys.exit(0)

def sendDisconnect(address, client):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        host, port = address
        s.connect((host, int(port)))
        s.send("SERVERISDISCONNECTING".encode())
    except OSError as e:
        if e.errno == 113:
            removeClient(client)
            print("-----------------------------------------------------------------------------")
            print("| It appears a receive client is hosted on Nike.                            |")
            print("| Nike has a firewall which prevents clusters from talking to Nike.         |")
            print("| Therefore, I am unable to send a disconnect command to the receive client.|")
            print("|                                                                           |")
            print("| Try running both clients on different clusters to see it working properly.|")
            print("|                                                                           |")
            print("| I'm sorry Dave.                                                           |")
            print("-----------------------------------------------------------------------------")
            os._exit(0)

def disconnectAllClients():
    """Disconnects all clients in the server"""
    for c,a,_,mode in clients:
        if mode == "R":
            if debug:
                print("Sending disconnect signal to " + str(a))
            sendDisconnect(a, c)
        closeConnection(c)
        removeClient(c)

def initiateExit(signal, frame):
    """Handles force shut down of server via Control-C"""
    print("Preparing to shut down server...")

    for thread in threading.enumerate():
        if threading.current_thread() is not threading.main_thread():
            thread.join()

    if threading.current_thread() is threading.main_thread():
        disconnectAllClients()
    sys.exit(0)

def sendMode(client, address, send_to_id):
    clients.append((client, address, 0, "S"))
    if debug:
        print("Client " + str(address) + " is in send mode. Send to: " + str(send_to_id))
    for _,address,id,mode in clients:
        if id == send_to_id and mode == "R":
            client.send(str(address).encode())
            return
    if debug:
        print(str(send_to_id) + " was not found.")
    client.send("NOTFOUND".encode())
    closeConnection(client)
    sys.exit(0)

def receiveMode(client, address, custom_recv_port):
    clientId = random.randint(1, 13337)
    if debug:
        print("Client " + str((address[0], int(custom_recv_port[1]))) + " is in receive mode. ID: " + str(clientId))

    clients.append((client, (address[0], int(custom_recv_port[1])), clientId, "R"))
    client.send(str(clientId).encode())

def handleClients(client, address):
    data = client.recv(4096)
    data = data.decode("UTF-8").strip()
    if debug:
        print(str(address) + " sent data: " + data)

    if data[0:1] == "S":
        sendMode(client, address, int(data[1:]))
    elif data[0:1] == "R":
        custom_recv_port = data.split(" ")
        receiveMode(client, address, custom_recv_port)
    else:
        if debug:
            print(str(address) + " didn't send a proper code.")
    try:
        while True:
            client.send("ping".encode())
    except socket.error as e:
        if debug:
            print(str(address) + " has disconnected.")
        removeClient(client)
            
# Set up argparse for debug information
parser = argparse.ArgumentParser(description="Use for debug only")
parser.add_argument("--debug", help="Debug information", action="store_true")
parser.add_argument("--port", help="Designate port to run the server.")
args = parser.parse_args()

if args.debug:
    debug = True
else:
    print("To see server messages, launch the server with '$ python3 ftserver.py --debug'")
    
if args.port:
    SERVER_PORT = int(args.port)
    if debug:
        print("Server running on custom port " + args.port)
else:
    if debug:
        print("Server is running on default port 47682.")

# Catch SIGINT (Control-C)
signal.signal(signal.SIGINT, initiateExit)

# Setup the connection
SERVER_ADDR = (SERVER_HOST, SERVER_PORT)
connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
connection.bind(SERVER_ADDR)
connection.listen(10)

while True:
    client, address = connection.accept() # Accept the incoming connection
    if debug:
        print("Incoming client connection: " + str(address))
    t = threading.Thread(target=handleClients, args=(client, address)) # Create a new thread 
    t.start() # Start the new thread