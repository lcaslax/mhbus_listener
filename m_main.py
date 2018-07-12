#! /usr/bin/python

# -------------------------------------------------------------------------------
# Name:        mhbus_listener
# Purpose:     Home automation system with bticino MyHome(R)
#
# Author:      Flavio Giovannangeli
# e-mail:      flavio.giovannangeli@gmail.com
#
# Created:     15/10/2013
# Updated:     25/11/2014
# Licence:     GPLv3
# -------------------------------------------------------------------------------

# Copyright (C) 2013 Flavio Giovannangeli

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Thanks to MyOpen Community (http://www.myopen-legrandgroup.com/) for support.

__version__ = '2.1.0_beta02'

import re
import time
import os, sys
import m_eventsman as EvMan
import xml.etree.ElementTree as ET
import logging
import logging.handlers
from logging.config import fileConfig
from cl_btbus import MyHome
import m_config


# Tunable parameters
ACK = '*#*1##'                # Acknowledge (OPEN message OK)
NACK = '*#*0##'               # Not-Acknowledge (OPEN message KO)
MONITOR = '*99*1##'           # Monitor session
COMMANDS = '*99*0##'          # Commands session
CFGFILENAME = 'mhblconf.xml'  # Configuration file name

ALLXML_FILE = ET.parse(CFGFILENAME)
DEBUG = int(ALLXML_FILE.find("log[@file]").attrib['printOnScreen'])                      # Debug


# F U N C T I O N S #

def main():
    ############
    ### MAIN ###
    ############
    try:
        # ***********************************************************
        # ** LETTURA PARAMETRI NECESSARI DA FILE DI CONFIGURAZIONE **
        # ***********************************************************
        # Lettura indirizzo IP e porta del gateway ethernet con priorita' 1
        mhgateway_ip = ALLXML_FILE.find("gateways/gateway[@priority='1']").attrib['address']
        mhgateway_port = ALLXML_FILE.find("gateways/gateway[@priority='1']").attrib['port']
        # Lettura percorso e nome del file di log
        flog = ALLXML_FILE.find("log[@file]").attrib['file']

        # Istanzia log
        logtype = ALLXML_FILE.find("log[@type]").attrib['type']
        logLevelName = ALLXML_FILE.find("log[@Level]").attrib['Level']        
        logger = logging.getLogger()
        handler = logging.handlers.TimedRotatingFileHandler(flog, when=logtype, interval=1, backupCount=0)
        formatter = logging.Formatter('%(asctime)s %(name)-6s %(levelname)-8s %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        LEVELS = { 'debug':logging.DEBUG,
            'info':logging.INFO,
            'warning':logging.WARNING,
            'error':logging.ERROR,
            'critical':logging.CRITICAL,
        }
        livelloLog = LEVELS.get(logLevelName)
        logger.setLevel(livelloLog)
                
        m_config.init();        
            
        # Lettura dei 'CHI' da filtrare.
        iwhofilter = map(int, ALLXML_FILE.find("log[@file]").attrib['who_filter'].split(','))
        # Lettura parametri di traduzione del 'CHI'.
        strawho = 'N' # 'NO' default
        strawho = ALLXML_FILE.find("log[@file]").attrib['who_translate']
        strawholang = 'ITA' # 'ITA' default
        strawholang = ALLXML_FILE.find("log[@file]").attrib['who_lang']
        
        # ***********************************************************
        # ** CONNESSIONE AL GATEWAY                                **
        # ***********************************************************
        logging.warn('mhbus_listener v.' + __version__ + ' started.')
        # Controllo presenza parametri necessari
        if mhgateway_ip and mhgateway_port and flog:
            # Instanziamento classe MyHome
            mhobj = MyHome(mhgateway_ip,mhgateway_port)
            # Connessione all'impianto MyHome...
            smon = mhobj.mh_connect()
            if smon:
                # Controllo risposta del gateway
                if mhobj.mh_receive_data(smon) == ACK:
                    logging.info('bticino gateway ' + mhgateway_ip + ' connected.')
                    # OK, attivazione modalita' 'MONITOR'
                    mhobj.mh_send_data(smon,MONITOR)
                    # Controllo risposta del gateway
                    if mhobj.mh_receive_data(smon) == ACK:
                        # Modalita' MONITOR attivata.
                        logging.info('OK, Ready!')
                        # ***********************************************************
                        # ** ASCOLTO BUS...                                        **
                        # ***********************************************************
                        afframes = []
                        while smon:
                            # Lettura dati in arrivo dal bus
                            frames = mhobj.mh_receive_data(smon)
                            if frames != '':
                                # Controllo prima di tutto che la frame open sia nel formato corretto (*...##)
                                if (frames.startswith('*') and frames.endswith('##')):
                                    # OK, controllo se si tratta di ACK o NACK, che vengono ignorati.
                                    if not (frames == ACK or frames == NACK):
                                        # Separazione frame (nel caso ne arrivino piu' di uno)
                                        frames = frames.split('##')
                                        for frame in frames:
                                            if frame:
                                                # Viene reinserito il terminatore open
                                                msgOpen = frame + '##'
                                                # Extract WHO and write log
                                                who = mhobj.mh_get_who(msgOpen)
                                                if DEBUG == 1:
                                                    print 'Frame open in transito: [%s] - CHI rilevato: [%s]' % (msgOpen, str(who))
                                                # Se il 'CHI' non e' tra quelli da filtrare, scrivi il log
                                                # e gestisci eventuale azione da compiere.
                                                if who not in iwhofilter:
                                                    # Controlla se e' richiesta la traduzione del 'CHI'
                                                    if strawho == 'Y':
                                                        logging.debug(msgOpen + ';' + mhobj.mh_get_who_descr(who,strawholang))
                                                    else:
                                                        logging.debug(msgOpen)
                                                    # Gestione voci antifurto
                                                    if who == 5 and msgOpen != '*5*3*##':
                                                        if msgOpen not in afframes:
                                                            afframes.append(msgOpen)
                                                        else:
                                                            continue
                                                        if msgOpen == '*5*5*##' or msgOpen == '*5*4*##':
                                                            # Reset lista af
                                                            afframes = []
                                                    # Controllo eventi...
                                                    EvMan.ControlloEventi(msgOpen, logging)
                                else:
                                    # Frame non riconosciuta!
                                    logging.warn(msgOpen + ' [STRINGA OPENWEBNET NON RICONOSCIUTA!]')
                            else:
                                # Non ricevo piu' nulla!
                                logging.warn(str(frames) + ' - ' + str(smon))
                    else:
                        # KO, non e' stato possibile attivare la modalita' MONITOR, impossibile proseguire.
                        logging.fatal('IL GATEWAY %s HA RIFIUTATO LA MODALITA'' MONITOR. ARRIVEDERCI!') % (mhgateway_ip)
                        ExitApp()
                else:
                    # KO, il gateway non ha risposto nel tempo previsto, impossibile proseguire.
                    logging.error('IL GATEWAY %s NON HA RISPOSTO NEL TEMPO PREVISTO. ARRIVEDERCI!') % (mhgateway_ip) 
                    ExitApp()
            else:
                # KO, il gateway non e' stato trovato, impossibile proseguire.
                #print 'NESSUN GATEWAY BTICINO TROVATO ALL''INDIRIZZO ' + mhgateway_ip + '! ARRIVEDERCI!'
                logging.fatal('NESSUN GATEWAY BTICINO TROVATO ALL''INDIRIZZO %s! ARRIVEDERCI!') % (mhgateway_ip)
                ExitApp()
        else:
            # KO, errore nella lettura di parametri indispensabili, impossibile proseguire.
            logging.fatal('ERRORE NELLA LETTURA DI PARAMETRI INDISPENSABILI. ARRIVEDERCI!')
            ExitApp()
    except Exception, err:
        if DEBUG == 1:
            print 'Errore in f.main! [' + str(sys.stderr.write('ERROR: %s\n' % str(err))) + ']'
            logging.fatal('Errore in f.main! [' + str(sys.stderr.write('ERROR: %s\n' % str(err))) + ']')


def ExitApp():
    try:
        # Close socket.
        smon.close
    except:
        # Exit
        if not logging.warn('DISCONNESSO DAL GATEWAY. ARRIVEDERCI!'):
            print 'DISCONNESSO DAL GATEWAY. ARRIVEDERCI!'
        pushover_service('mhbus_listener ' + __version__ + ' closed!')
        sys.exit()


if __name__ == '__main__':
    main()
