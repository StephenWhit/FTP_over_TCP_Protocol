Danny Lee (811080861)
Stephen Whitcomb (811330368)

Description: This project helps facilitate a peer-to-peer
transfer protocol over TCP. The server regulates who can
connect to whom and provides IP addresses for clients to
talk to each other. The clients then facilitate the
file transfer process and ensures that correct files
are transferred.

Running the program:
        SERVER: $ python3 ftserver.py [--port PORT] [--debug]
        CLIENT: $ python3 ftclient.py --server HOST:PORT
                  [-p PORT] [--receive] [--send ID FILE]
                  [-c CNUM] [-s SIZE] [--debug]

Protocol Documentation:
This protocol utilizes basic text as a means of communication
between clients and the server. Clients communicate with
each other using reserved phrases in the header such as
AIIGHTFAMITSALLGUCCI to signify that both clients have agreed
on specifications and are ready to proceed with the transfer.

Upon initial connection, the sender client sends a header
with information documenting the settings it is currently
running under. The receiver client will then compare its settings
to the sender's and relaying any conflicting information back,
such as if one client's buffer size is bigger than another.

Once said information has been agreed upon, the file is split
based on byte offset per thread and a header containing a sender ID
and the current chunck offset is appended to the data. The sender
client will attempt to always max out theb buffer so that the entire
network and buffer is utilized. On the receiver side, each thread is
assigned a temporary file for it to write whatever data it obtains.
This data is sorted and labeled based on byte offset and sender ID.
Once the sender client relays that it has successfully sent all of
the file chunks, the receiver will then initiate a clean up phase
where it puts together the pieces of each file to recreate the
original file.