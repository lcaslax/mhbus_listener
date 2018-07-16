#! /usr/bin/python

# << Events Manager Module for mhbus_lister >>

# Thanks to MyOpen Community (http://www.myopen-bticino.it/) for support.

# Copyright (C) 2012 Flavio Giovannangeli
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

# e-mail:


import ConfigParser
import httplib, urllib
import logging
import os, sys
import platform
import string
import sys
import time
import traceback

import requests
from requests.exceptions import ConnectionError

import cPickle as pickle
from cl_btbus import MyHome
from cl_email import EmailSender
from cl_log import Log
import json as simplejson
from m_config import StoreEnergie
import m_config as MCFG
from m_main import ALLXML_FILE
from m_main import DEBUG
import xml.etree.ElementTree as ET


#from m_main import statusChannel
# Optionl module for GSM function.
try:
    from cl_gsmat import GsmDevice
    gsm_module_available = True
except ImportError:
    gsm_module_available = False
# Optional module for Twitter function.
try:
    from cl_twtapi import TwitterApi
    twt_module_available = True
except ImportError:
    twt_module_available = False


# Tunable parameters
CFGFILENAME = 'mhblconf.xml'  # Configuration file name

tidt = []

########################
### CONTROLLO EVENTI ###
########################

def ControlloEventi(msgOpen, logging):
    # GESTIONE EVENTI E AZIONI #
    trigger = msgOpen
    eneropt = string
    enerval = float()
    try:
        # Se CHI=4 estrazione dati di temperatura.
        if trigger.startswith('*#4*'):
            trigger, nzo, vt = gestioneTermo(trigger)
        elif trigger.startswith('*#18*'):
            trigger, nto, vto, dat = gestioneEnergia(trigger)
            
        # Cerca trigger evento legato alla frame open ricevuta.
        
        #for elem in ALLXML_FILE.find("alerts/alert[@trigger='" + trigger + "']"):
        #s_trigger = "alerts/alert[@trigger='%s']" % (trigger)
        #for elem in ALLXML_FILE.iterfind(s_trigger):
        
        elem = MCFG.alertElement.get(trigger)
        if elem != None:
            # Estrai canale
            channel = elem.attrib['channel']
            
            # Se trigger di TEMPERATURA estrai parametri e verificali
            if trigger.startswith('TS'):
                tempdta = elem.attrib['data'].split('|')
                tempopt = tempdta[1]
                tempval = float(tempdta[2])
                #logging.debug('TS: channel [' + channel + '] tempdta [' + tempdta + '] tempopt [' + tempopt + '] tempval [' + tempval + '] trigger [' + trigger + ']')

                vt = PrepareValuesToSend(vt, trigger, tempopt, tempval)
                if (vt is None) or (str(vt).strip()==""):  #stringa vuota
                   return
                    
            #- TE5x energia istantanea (x e' il toroide)
            #- TE4x energia del giorno precedente
            #- TE3x energia mese precedente        
            elif trigger.startswith('TE5'):
                enerdta = elem.attrib['data'].split('|')
                eneropt = enerdta[1]
                enerval = float(enerdta[2])
                
                vto = PrepareValuesToSend(vto, trigger, eneropt, enerval)
                if (vto is None) or (str(vto).strip()==""):  #stringa vuota
                   return
             
            if MCFG.enabledChannel.get(channel):
                # Inseriti valori dinamici nella stringa
                data = elem.attrib['data']
                s_temp = data.split("|");
                testoDaInviare = s_temp[0]
                
                #SE TEMP preparo il testo da inviare 
                if trigger.startswith('TS'):                     
                    nomeSonda = str(nzo)
                    try:
                        testoDaInviare = testoDaInviare.replace('{temp}', str(vt))  
                    except Exception, err:
                        if DEBUG == 1:
                            print 'Non trovato {temp} da parsificare nel file config'
                    try:
                        #cfg_sonda = ALLXML_FILE.find("sondeTemp/sonda[@type='%s']") % (str(nzo))
                        cfg_sonda = MCFG.elencoSondeTemp.get(str(nzo))
                        nomeSonda = cfg_sonda.attrib['data']
                        testoDaInviare = testoDaInviare.replace('{sonda}', str(nomeSonda))     
                        #testoDaInviare = str(s_temp[1]) + ' | Sonda ' + str(nomeSonda) + ' indica ' + str(vt) + ' gradi '
                    except Exception, err:
                        if DEBUG == 1:
                            print 'Non trovato sondeTemp e {sonda} nel file config'
                        logging.info('Sonda [%s] non trovata' ) % (str(nzo))
                    if DEBUG == 1:
                        print 'TEMP sending: ' + testoDaInviare
                #SE ENERGIA preparo il testo da inviare
                elif (trigger.startswith('TE4') or trigger.startswith('TE3')):
                    testoDaInviare = testoDaInviare + str(dat) + ' ' + str(vto)
                    if DEBUG == 1:
                        print 'EN sending: ' + testoDaInviare 
                # Trovato evento, verifica come reagire.
                elif (trigger.startswith('TE5') or trigger.startswith('TE2')):
                    testoDaInviare = testoDaInviare + str(vto)
                    if DEBUG == 1:
                        print 'EN sending: ' + testoDaInviare
                invioNotifiche(data, channel, trigger, testoDaInviare, logging)
            else:
                logging.debug('Alert non gestito causa canale [%s] non abilitato!' % channel)
    except Exception, err:
        if DEBUG == 1:
            print 'Errore in f.ControlloEventi! [' + str(sys.exc_info()) + ']'
        logging.warn('Errore in f.ControlloEventi! [' + str(sys.exc_info()) + ']')

#Routine per la gestione Termo
def gestioneTermo(trigger):
    ####################################################################
    # Recupero precedenti valori di temperatura memorizzati.
    # Se non disponibili e' prima volta. L'informazione della
    # temperatura viene inviata dalle sonde sul bus ogni 15 minuti.
    # L'ultimo valore di temp. viene storicizzato e confrontato con
    # la successiva lettura, questo perche' il trigger deve scattare
    # una sola volta finche' la condizione rimane VERA.
    ####################################################################
    # Lettura sonde
    nzo = 0
    vt = float(0.0)
    if trigger.split('*')[3] == '15':
        #################
        # Sonda esterna #
        #################
        # Numero sonda
        nzo = int(trigger.split('*')[2][0:1])
        # Lettura temperatura
        vt = fixtemp(trigger.split('*')[5][0:4])
        # Lettura ultimi dati registrati
        try:
            tedt = []
            #se richiesto scrive valori temporanei su file
            if (MCFG.writeTempTmpFile):
                tedt = pickle.load(open("tempdata.p", "rb"))
            else:
                tedt = MCFG.fileTempTmp
           
            # Presenza di ultimo dato storicizzato. Confronta.
            if nzo == tedt[0] and vt == tedt[1]:
                # Valori invariati dalla precedente lettura, no trigger!
                exit
        except Exception:
            # Nessun dato storicizzato, scrivi quello appena letto.
            tedt.append(nzo)
            tedt.append(vt)
            #se richiesto scrive valori temporanei su file
            if (MCFG.writeTempTmpFile):
                pickle.dump(tedt,open("tempdata.p", "wb"))
            else:
                MCFG.fileTempTmp = tedtM
            # OK trigger
            trigger = 'TSE' + str(nzo)
    elif trigger.split('*')[3] == '0':
        #################
        # Sonda interna #
        #################
        # Numero zona
        nzo = trigger.split('*')[2][0:1]
        # Lettura temperatura
        vt = fixtemp(trigger.split('*')[4][0:4])
        if DEBUG == 1:
            print 'TEMP: Sonda interna [%s] rilevata temp  [%s]' % (str(nzo), str(vt))
        # Lettura ultimi dati registrati
        try:
            ###tidt = []
            i = 0
            #se richiesto scrive valori temporanei su file
            if (MCFG.writeTempTmpFile):
                tidt = pickle.load(open("tempdata.p", "rb"))
            else:
                tidt = MCFG.fileTempTmp
            
            b_writeTemp = 1;
            for elem in tidt:
                if i%2 == 0:
                    if DEBUG == 1:
                        print 'TEMP: Sonda interna | Precedenti valori: sonda=[%s]  temp=[%s]' % (str(tidt[i]), str(tidt[i+1]))
                    if nzo == tidt[i]:
                        if vt == float(tidt[i+1]):
                            #temp della sonda invariata non modifico nulla
                            b_writeTemp = 0
                            exit
                        else:
                            # la temp della sonda e' cambiata salvala
                            if DEBUG == 1:
                                print 'TEMP: %s della sonda %s e cambiata. lettura precedente: %s' % (str(vt), str(nzo), str(tidt[i+1]))
                            trigger = 'TSZ' + str(nzo) 
                            b_writeTemp = 0
                            tidt[i+1] = str(vt)
                            writeTemFile(tidt)  
                i = i + 1      
            # se non ho trovato la sonda nel file aggiorno il file
            if b_writeTemp == 1:
                if DEBUG == 1:
                    print 'TEMP: Sonda %s non presente nel file valore salvato: %s' % (str(nzo), str(vt))
                trigger = 'TSZ' + str(nzo)  
                tidt.append(nzo)
                tidt.append(str(vt))
                writeTemFile(tidt)             
        except Exception:
            if DEBUG == 1:
                print 'Errore in f.ControlloEventi! [%s] File tempdata.p inesistente?' % (str(sys.exc_info()))
            # Nessun dato storicizzato, scrivi quello appena letto.
            tidt = []
            tidt.append(nzo)
            tidt.append(str(vt))
            #se richiesto scrive valori temporanei su file
            if (MCFG.writeTempTmpFile):
                pickle.dump(tidt,open("tempdata.p", "wb"))
            else:
                MCFG.fileTempTmp = tidt
            # OK trigger
            trigger = 'TSZ' + str(nzo)
            if DEBUG == 1:
                print'TEMP: Sonda interna | Nessun dato storicizzato trigger =  [%s]' % (str(trigger))
    else:
        # Ignorare altre frame termoregolazione non gestite.
        None
    return trigger, nzo, vt


#Routine per la gestione dell'energia
def gestioneEnergia(trigger):
    nto = 0
    vto = float(0.0)
    dat = 0
    if trigger.split('*')[3] == '113':
        # Numero toroide
        nto = int(trigger.split('*')[2][-1])
        #print nto
        # Lettura dati energia
        vto = trigger.split('*')[4]
        vto = int(vto[:-2])
        #print vto
        # Trigger
        trigger = 'TE5' + str(nto)
        #print trigger
    elif (trigger.split('*')[3][:3]) == '511' and trigger.split('*')[4] == '25':  #energia totale per giorno specifico
        # Numero toroide
        nto = int(trigger.split('*')[2][-1])
        #print nto
        # Lettura dati energia
        vto = fixener(trigger.split('*')[5])
        dat = trigger.split('*')[3]
        dat = dat.split('#')[2] + '/' + dat.split('#')[1]
        trigger = 'TE4' + str(nto)
        #print trigger
    elif trigger.split('*')[3][:2] == '52':   #energia totale per mese specifico
        # Numero toroide
        nto = int(trigger.split('*')[2][-1])
        #print nto
        # Lettura dati energia
        vto = fixener(trigger.split('*')[4])
        dat = trigger.split('*')[3]
        dat = dat.split('#')[2] + '/' + dat.split('#')[1]
        trigger = 'TE3' + str(nto)
        #print trigger
    elif trigger.split('*')[3] == '53':   #energia parziale del mese corrente
        # Numero toroide
        nto = int(trigger.split('*')[2][-1])
        #print nto
        # Lettura dati energia
        vto = fixener(trigger.split('*')[4])
        trigger = 'TE2' + str(nto)
        #print trigger
        # Lettura parametri trigger
    else:
        # Altre frame energia non gestite
        None
        # Lettura canale
        #channel = elem.attrib['channel']
    return trigger, nto, vto, dat   
    

#invio notifiche
def invioNotifiche(data, channel, trigger, testoDaInviare, logging):
    if channel == 'POV':
        # ***********************************************************
        # ** Pushover channel                                      **
        # ***********************************************************
        povdata = data.split('|')
        if pushover_service(testoDaInviare) == True:
            logging.info('Inviato messaggio pushover a seguito di evento ' + trigger)
        else:
            logging.warn('Errore invio messaggio pushover a seguito di evento ' + trigger + "(" + testoDaInviare + ")")
    elif channel == 'SMS':
        # ***********************************************************
        # ** SMS channel (a GSM phone is required on RS-232)       **
        # ***********************************************************
        smsdata = data.split('|')
        if sms_service(smsdata[0],smsdata[1]) == True:
            logging.info('Inviato/i SMS a ' + smsdata[0] + ' a seguito di evento ' + trigger)
        else:
            logging.warn('Errore invio SMS a seguito di evento ' + trigger)
    elif channel == 'TWT':
        # ***********************************************************
        # ** Twitter channel                                       **
        # ***********************************************************
        twtdata = data.split('|')
        if twitter_service(twtdata[0],testoDaInviare) == True:
            logging.info('Inviato tweet a ' + twtdata[0] + ' a seguito di evento ' + trigger)
        else:
            logging.warn('Errore invio tweet a seguito di evento ' + trigger)
    elif channel == 'EML':
        # ***********************************************************
        # ** e-mail channel                                        **
        # ***********************************************************
        emldata = data.split('|')
        if DEBUG == 1:
            print 'Tentativo invio email [' + str(emldata[0]) + '] con testo ' + testoDaInviare 
        
        if email_service(emldata[0],'mhbus_listener alert',testoDaInviare) == True:
            logging.info('Inviata/e e-mail a ' + str(emldata[0]) +  ' a seguito di evento ' + trigger)
        else:
            logging.warn('Errore invio e-mail a ' + str(emldata[0]) + ' a seguito di evento ' + trigger + "(" + testoDaInviare + ")")
    elif channel == 'BUS':
        # ***********************************************************
        # ** SCS-BUS channel                                       **
        # ***********************************************************
        busdata = data.split('|')
        if opencmd_service(busdata[0]) == True:
            logging.info('Eseguito/i comando/i OPEN preimpostato/i a seguito di evento ' + trigger)
        else:
            logging.warn('Errore esecuzione comando/i OPEN preimpostato/i a seguito di evento ' + trigger )
    elif channel == 'BAT':
        # ***********************************************************
        # ** Batch channel                                         **
        # ***********************************************************
        busdata = data.split('|')
        if batch_service(busdata[0]) == True:
            logging.info('Eseguito batch a seguito di evento ' + trigger)
        else:
            logging.warn('Errore esecuzione batch a seguito di evento ' + trigger)
    elif channel == 'IFT':
        # ***********************************************************
        # ** INVIO ALERT TRAMITE IFTT                              **
        # ***********************************************************
        iftdata = data.split('|')
        if ifttt_service(iftdata[0],iftdata[1]) == True:
           logging.debug('Inviato Ifttt a ' + iftdata[0] + ' a seguito di evento ' + trigger)
        else:
           logging.warn('Errore invio Ifttt a seguito di evento ' + trigger)
    else:
        # Error
        logging.warn('Canale di notifica non riconosciuto! [' + action + ']')
        if DEBUG == 1:
            print 'Nessun canale conosciuto. NON spedito [' + testoDaInviare +']'
        
### @TODO Refectoring con EnergiaGRATERTHAN  
def EnergiaLESSTHAN(vto, enerval, key, precVal):
    sE= StoreEnergie()
    if DEBUG:
        print "EnergiaLESSTHAN: vto %s enerval %s key %s precVal %s" % (str(vto), enerval, key, precVal)
     # LESS THAN
    if not vto < enerval:
        #Esisteva una chiave--> cancello e segnalo che siamo usciti dall'alert
        if precVal != None:
            vto = precVal
            sE.store.pop(key)
            return str(vto)
        else:
            return 'null'
    else:
        if precVal != None:
            minmax = precVal.split('|')
            if (float(minmax[0]) <= float(vto)):
                if (float(minmax[1]) >= float(vto)):
                    return 'null'
                else:
                    minmax[1] = str(vto)
                    if DEBUG:
                        print "EnergiaLESSTHAN: new max %s" % (minmax[1]) 
            else:
                minmax[0] = str(vto)
                if DEBUG:
                    print "EnergiaLESSTHAN: new min %s" % (minmax[0])
            sE.store[key] = str(minmax[0])+'|'+str(minmax[1])
        else:
            #MCFG.StoreEnergie[key] = str(vto)+'|'+str(vto)
            sE.store[key] = str(vto)+'|'+str(vto)
    return str(vto)

def EnergiaGRATERTHAN(vto, enerval, key, precVal):
    sE= StoreEnergie()
    if not vto > enerval:
        #Esisteva una chiave--> cancello e segnalo che siamo usciti dall'alert
        if precVal != None:
            vto = precVal
            sE.store.pop(key)
        else:
            return
    else:
        if precVal != None:
            minmax = precVal.split('|')
            if (float_int(minmax[0]) <= vto):
                if (float_int(minmax[1]) >= vto):
                    return
                else:
                    minmax[1] = str(vto)
            else:
                minmax[0] = str(vto)
            sE.store[key] = str(minmax[0])+'|'+str(minmax[1])
        else:
            #MCFG.StoreEnergie[key] = str(vto)+'|'+str(vto)
            sE.store[key] = str(vto)+'|'+str(vto)
    return str(vto)


def PrepareValuesToSend(vto, trigger, eneropt, enerval):
#<!------ START ----------------------------------------------------------------------------------------------------->
    key = trigger + '|' + eneropt+'|'+str(enerval)
    #logging.debug('TE5: channel [' + channel + '] tempdta [' + tempdta + '] tempopt [' + tempopt + '] tempval [' + tempval + '] trigger [' + trigger + ']')
    sE= StoreEnergie()
    #precVal = MCFG.StoreEnergie.get(key)
    precVal = sE.store.get(key)

    if eneropt == 'EQ':
        # EQUAL
        if not vto == enerval:
            return
    elif eneropt == 'LS':
        #if not vto < enerval:
        #    #Esisteva una chiave--> cancello e segnalo che siamo usciti dall'alert
        #    if precVal != None:
        #        vto = precVal
        #        sE.store.pop(key)
        #        return str(vto)
        #    else:
        #        return
        vto = EnergiaLESSTHAN(vto, enerval, key, precVal)
        if vto == 'null':
            return
    elif eneropt == 'LE':
        # LESS OR EQUAL
        ##if not vto <= enerval:
        ##    return
        vto = EnergiaLESSTHAN(vto, enerval, key, precVal)
        if vto == 'null':
            return
    elif eneropt == 'GR':
        vto = EnergiaGRATERTHAN(vto, enerval, key, precVal)
        if vto == 'null':
            return
        ##if not vto > enerval:
        ##    return
    elif eneropt == 'GE':
        ## GREATER OR EQUAL
        ##if not vto >= enerval:
        ##    return
        vto = EnergiaGRATERTHAN(vto, enerval, key, precVal)
        if vto == 'null':
            return
    else:
        if precVal != None:
            minmax = precVal.split('|')
            if (int(minmax[0]) <= vto):
                if (int(minmax[1]) >= vto):
                    return 
                else:
                    minmax[1] = str(vto)
                    if DEBUG:
                        print "EnergiaLESSTHAN: new max %s" % (minmax[1]) 
            else:
                minmax[0] = str(vto)
                if DEBUG:
                    print "EnergiaLESSTHAN: new min %s" % (minmax[0])
            sE.store[key] = str(minmax[0])+'|'+str(minmax[1])
        else:
            #MCFG.StoreEnergie[key] = str(vto)+'|'+str(vto)
            sE.store[key] = str(vto)+'|'+str(vto)   
 
    return str(vto)
#<!---- END --------------------------------------------------------------------------------------------------------------->



####################################################################################################
##########################
######### SERVICE
##########################
####################################################################################################

def pushover_service(pomsg):
    bOK = True
    try:
        conn = httplib.HTTPSConnection(MCFG.pov_poaddr)
        conn.request("POST", "/1/messages.json",
          urllib.urlencode({
            "token": MCFG.pov_poat,
            "user": MCFG.pov_pouk,
            "message": pomsg,
          }), { "Content-type": "application/x-www-form-urlencoded" })
        conn.close()
    except httplib.HTTPException as httpEx:
        sErr = "Pushover_service [" + MCFG.pov_poaddr + "] HTTPException " + str(httpEx) + " StackTrace  [" + sys.exc_info() + "]"
        print sErr
        logging.error(sErr)
        bOK = False
    except:
        sErr = "Pushover_service [" + MCFG.pov_poaddr + "] StackTrace  [" + sys.exc_info() + "]"
        print sErr
        logging.error(sErr)
        bOK = False
    finally:
        return bOK
        

def batch_service(batchdata):
    bOK = True
    try:
        import subprocess
        # Determina tipo sistema operativo
        ostype = platform.system()
        if ostype == 'Windows':
            esito = subprocess.call([batchdata])
            if esito != 0:
                bOK = False
        else:
            esito = subprocess.call(['.' + batchdata])
            if esito != 0:
                bOK = False
    except:
        bOK = False
    finally:
        return bOK


def sms_service(nums,smstext):
    bOK = True
    try:
        serport = ALLXML_FILE.find("channels/channel[@type='SMS']").attrib['serport']
        serspeed = ALLXML_FILE.find("channels/channel[@type='SMS']").attrib['serspeed']
        gsmobj = GsmDevice(serport,serspeed)
        numdest = nums.split(';')
        i = 0
        while i < len(numdest):
            if numdest[i]:
                if not gsmobj.send_sms(numdest[i],smstext) == True:
                    bOK = False
                i = i + 1
            else:
                break
    except Exception, err:
        bOK = False
        if DEBUG == 1:
            print sys.stderr.write('ERROR: %s\n' % str(err))
    finally:
        return bOK


def twitter_service(twtdest,twttext):
    bOK = True
    try:
        twdest = twtdest.split(';')
        if DEBUG == 1:
            print twdest
        # Instanziamento classe TwitterApi
        twtobj = TwitterApi(MCFG.twt_ckey,MCFG.twt_cset,MCFG.twt_atkey,MCFG.twt_atsec)
        i = 0
        while i < len(twdest):
            if twdest[i]:
                if DEBUG == 1:
                    print twdest[i],twttext
                if twdest[i].startswith('@'):
                    # Send a private tweet
                    if not twtobj.send_private_twt(twdest[i],twttext) == True:
                        bOK = False
                else:
                    # Send a public tweet
                    if not twtobj.send_public_twt(twttext) == True:
                        bOK = False
                time.sleep(2)
                i = i + 1
            else:
                break
    except Exception, err:
        bOK = False
        if DEBUG == 1:
            print sys.stderr.write('ERROR: %s\n' % str(err))
    finally:
        return bOK


def email_service(emldest,emlobj,emltext):
    bOK = True
    try:
        mailobj = EmailSender(em_smtpsrv,em_smtpport,em_smtpauth,em_smtpuser,em_smtppsw,em_smtptls,em_sender)
        if not mailobj.send_email(emldest,emlobj,emltext) == True:
            bOK = False
    except Exception, err:
        bOK = False
        logging.warn('Errore in invio email! [' + str(sys.exc_info()) + ']')
        if DEBUG == 1:
            print 'Errore in invio email! [' + str(sys.exc_info()) + ']'
        
    finally:
        return bOK


def opencmd_service(opencmd):
    bOK = True
    try:
        # Instanziamento classe MyHome
        mhobj = MyHome(MCFG.mhgateway_ip,MCFG.mhgateway_port)
        # Connessione all'impianto MyHome...
        scmd = mhobj.mh_connect()
        mhcmd  = opencmd.split(';')
        if scmd != None:
            time.sleep(1)
            if mhobj.mh_receive_data(scmd) == ACK:
                # OK, apertura sessione comandi
                mhobj.mh_send_data(scmd, COMMANDS)
                time.sleep(1)
                i = 0
                while i < len(mhcmd):
                    if mhcmd[i]:
                        if not mhobj.mh_send_data(scmd,mhcmd[i]) == True:
                            bOK = False
                        i = i + 1
                    else:
                        break
                # Chiudi sessione comandi
                scmd.close()
            else:
                bOK = False
        else:
            bOK = False
    except:
        bOK = False
    finally:
        return bOK


def fixtemp(vt):
    # Adatta il formato di temperatura
    # Controllo segno temperatura
    if vt[0:1] == '1':
        # Temp. negativa
        vt = float(vt[1:])*-1
    elif vt[0:1] == '0':
        # Temp. positiva
        vt = float(vt)
    else:
        # Errore!
        vt = 999
    # Mostra temperatura
    return vt/10


def writeTemFile(tidt):
    if DEBUG == 1:
        print 'scrivo ' + str(tidt)
    if (MCFG.writeTempTmpFile):
        pickle.dump(tidt,open("tempdata.p", "wb"))
    else:
        MCFG.fileTempTmp = tidt

def fixener(vto):
   # Adatta il formato di energia
   vto = vto[:-2]
   vto = round(float(vto)/1000 , 2)
   vto = str(vto)
   vto = vto.replace(".",",") + ' kWh'
   return vto

def ifttt_service(trigger,iftext):
    bOK = True
    try:
        if DEBUG == 1:
            print 'IFT_address: ' + IFT_address
        url = ift_address.format(e=trigger,k=ift_ckey)
        
        logging.debug('IFT Preparazione= trigger: ' + trigger + ' ckey ' + ift_ckey + ' url ' + url)
        if DEBUG == 1:
            print 'IFT Preparazione= trigger: ' + trigger + ' ckey ' + ift_ckey + ' url ' + url
        payload = {'value1': iftext}
        return requests.post(url, data=payload)
    except:
        bOK = False
    finally:
        return bOK

