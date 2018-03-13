'''
Created on 15 feb 2018

@author: lucslava
'''

__version__ = '2.0_beta'


import xml.etree.ElementTree as ET
from cl_btbus import MyHome
from time import sleep


# Tunable parameters
ACK = '*#*1##'                # Acknowledge (OPEN message OK)
NACK = '*#*0##'               # Not-Acknowledge (OPEN message KO)
MONITOR = '*99*1##'           # Monitor session
COMMANDS = '*99*0##'          # Commands session
CFGFILENAME = 'mhblconf.xml'  # Configuration file name

ALLXML_FILE = ET.parse(CFGFILENAME)
DEBUG = int(ALLXML_FILE.find("log[@file]").attrib['printOnScreen']) 


def main():
    ############
    ### MAIN ###
    ############
    # ***********************************************************
    # ** LETTURA PARAMETRI NECESSARI DA FILE DI CONFIGURAZIONE **
    # ***********************************************************
    # Lettura indirizzo IP e porta del gateway ethernet con priorita' 1
    mhgateway_ip = ALLXML_FILE.find("gateways/gateway[@priority='1']").attrib['address']
    mhgateway_port = ALLXML_FILE.find("gateways/gateway[@priority='1']").attrib['port']

    while (True):
        try:    
            # Instanziamento classe MyHome
            mhobj = MyHome("127.0.0.1",mhgateway_port)
            # Connessione all'impianto MyHome...
            smon = mhobj.mh_rcv_connections()
            mhobj.mh_send_data(smon,ACK)
            if mhobj.mh_receive_data(smon) != MONITOR:
                print "niente monitor? Esco"
                exit
            mhobj.mh_send_data(smon,ACK)
            f = open("serverTest.p", "rb")
            lines = f.readlines()
            while smon and lines != []:
                for x in lines:
                    content = x.strip()  
                    mhobj.mh_send_data(smon,content)
                    sleep(0.5)
                sleep(1)
                lines = f.readlines()
            mhobj.mh_closeConnect()            
        except Exception, err:
            print "Err: %s" % (str(err))
        print "Esco ..."

if __name__ == '__main__':
    main()

