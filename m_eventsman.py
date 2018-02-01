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

# e-mail:flavio.giovannangeli@gmail.com


import time
import os, sys
import platform
import ConfigParser
import httplib, urllib
import cPickle as pickle
import json as simplejson
import xml.etree.ElementTree as ET
import requests
from cl_log import Log
from cl_btbus import MyHome
from cl_email import EmailSender
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
DEBUG = 1                     # Debug
CFGFILENAME = 'mhblconf.xml'  # Configuration file name

tidt = []

########################
### CONTROLLO EVENTI ###
########################

def ControlloEventi(msgOpen, logging):
    # GESTIONE EVENTI E AZIONI #
    trigger = msgOpen
    try:
        # Lettura percorso e nome del file di log.

        # Se CHI=4 estrazione dati di temperatura.
        if trigger.startswith('*#4*'):
            trigger, nzo, vt = gestioneTermo(trigger)
        elif trigger.startswith('*#18*'):
            trigger, nto, vto  = gestioneEnergia(trigger)
            
        # Cerca trigger evento legato alla frame open ricevuta.
        for elem in ET.parse(CFGFILENAME).iterfind("alerts/alert[@trigger='" + trigger + "']"):
            # Estrai canale
            channel = elem.attrib['channel']
            # Se trigger di temperatura estrai parametri e verificali
            if trigger.startswith('TS'):
                tempdta = elem.attrib['data'].split('|')
                tempopt = tempdta[1]
                tempval = float(tempdta[2])
                #logging.debug('TS: channel [' + channel + '] tempdta [' + tempdta + '] tempopt [' + tempopt + '] tempval [' + tempval + '] trigger [' + trigger + ']')

                if tempopt == 'EQ':
                    # EQUAL
                    if not vt == tempval:
                        break
                elif tempopt == 'LS':
                    # LESS THAN
                    if not vt < tempval:
                        break
                elif tempopt == 'LE':
                    # LESS OR EQUAL
                    if not vt <= tempval:
                        break
                elif tempopt == 'GR':
                    # GREATER THAN
                    if not vt > tempval:
                        break
                elif tempopt == 'GE':
                    # GREATER OR EQUAL
                    if not vt >= tempval:
                        break
            #- TE5x energia istantanea (x e' il toroide)
            #- TE4x energia del giorno precedente
            #- TE3x energia mese precedente        
            elif trigger.startswith('TE5'):
                enerdta = elem.attrib['data'].split('|')
                eneropt = enerdta[1]
                enerval = float(enerdta[2])
                #logging.debug('TE5: channel [' + channel + '] tempdta [' + tempdta + '] tempopt [' + tempopt + '] tempval [' + tempval + '] trigger [' + trigger + ']')

                if eneropt == 'EQ':
                    # EQUAL
                    if not vto == enerval:
                        break
                elif eneropt == 'LS':
                    # LESS THAN
                    if not vto < enerval:
                        break
                elif eneropt == 'LE':
                    # LESS OR EQUAL
                    if not vto <= enerval:
                        break
                elif eneropt == 'GR':
                    # GREATER THAN
                    if not vto > enerval:
                        break
                elif eneropt == 'GE':
                    # GREATER OR EQUAL
                    if not vto >= enerval:
                        break    

            # Controlla stato del canale
            status = ET.parse(CFGFILENAME).find("channels/channel[@type='" + channel + "']").attrib['enabled']
            if status == "Y":
                # Inseriti valori dinamici nella stringa
                data = elem.attrib['data']
                s_temp = data.split("|");
                testoDaInviare = s_temp[0]
                
                #se temperatura preparo il testo da inviare 
                if trigger.startswith('TS'):                     
                    nomeSonda = str(nzo)
                    try:
                        testoDaInviare = testoDaInviare.replace('{temp}', str(vt))  
                    except Exception, err:
                        if DEBUG == 1:
                            print 'Non trovato temp da parsificare nel file config'
                    try:
                        cfg_sonda = ET.parse(CFGFILENAME).find("sondeTemp/sonda[@type='" + str(nzo) + "']")
                        nomeSonda = cfg_sonda.attrib['data']
                        testoDaInviare = testoDaInviare.replace('{sonda}', str(nomeSonda))     
                        #testoDaInviare = str(s_temp[1]) + ' | Sonda ' + str(nomeSonda) + ' indica ' + str(vt) + ' gradi '
                    except Exception, err:
                        if DEBUG == 1:
                            print 'Non trovato sondeTemp e sonda nel file config'
                    if DEBUG == 1:
                        print 'TEMP sending: ' + testoDaInviare
                #se energia preparo il testo da inviare
                elif trigger.startswith('TE'):
                    testoDaInviare = testoDaInviare + str(vto)         ######## mod andrea
                    if DEBUG == 1:
                        print 'EN sending: ' + testoDaInviare 
                # Trovato evento, verifica come reagire.
                invioNotifiche(data, channel, trigger, testoDaInviare, logging)
            else:
                logging.debug('Alert non gestito causa canale <' + channel + '> non abilitato!')
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
            tedt = pickle.load(open("tempdata.p", "rb"))
            # Presenza di ultimo dato storicizzato. Confronta.
            if nzo == tedt[0] and vt == tedt[1]:
                # Valori invariati dalla precedente lettura, no trigger!
                exit
        except Exception:
            # Nessun dato storicizzato, scrivi quello appena letto.
            tedt.append(nzo)
            tedt.append(vt)
            pickle.dump(tedt,open("tempdata.p", "wb"))
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
            print 'TEMP: Sonda interna [' + str(nzo) + '] rilevata temp  [' + str(vt) + ']'
        # Lettura ultimi dati registrati
        try:
            ###tidt = []
            i = 0
            tidt = pickle.load(open("tempdata.p", "rb"))
            b_writeTemp = 1;
            for elem in tidt:
                if i%2 == 0:
                    if DEBUG == 1:
                        print 'TEMP: Sonda interna | Precedenti valori: sonda=[' + str(tidt[i]) + ']  temp=[' + str(tidt[i+1]) + ']'
                    if nzo == tidt[i]:
                        if vt == float(tidt[i+1]):
                            #temp della sonda invariata non modifico nulla
                            b_writeTemp = 0
                            exit
                        else:
                            # la temp della sonda e' cambiata salvala
                            if DEBUG == 1:
                                print 'TEMP: ' + str(vt) + ' della sonda ' + str(nzo) + ' e cambiata.\' lettura precedente: ' + str(tidt[i+1])
                            trigger = 'TSZ' + str(nzo) 
                            b_writeTemp = 0
                            tidt[i+1] = str(vt)
                            writeTemFile(tidt)  
                i = i + 1      
            # se non ho trovato la sonda nel file aggiorno il file
            if b_writeTemp == 1:
                if DEBUG == 1:
                    print 'TEMP: Sonda ' + str(nzo) + ' non presente nel file valore salvato: ' + str(vt)
                trigger = 'TSZ' + str(nzo)  
                tidt.append(nzo)
                tidt.append(str(vt))
                writeTemFile(tidt)             
        except Exception:
            if DEBUG == 1:
                print 'Errore in f.ControlloEventi! [' + str(sys.exc_info()) + '] File tempdata.p inesistente?'
            # Nessun dato storicizzato, scrivi quello appena letto.
            tidt = []
            tidt.append(nzo)
            tidt.append(str(vt))
            pickle.dump(tidt,open("tempdata.p", "wb"))
            #writeTemFile(tidt)
            # OK trigger
            trigger = 'TSZ' + str(nzo)
            if DEBUG == 1:
                print'TEMP: Sonda interna | Nessun dato storicizzato trigger =  [' + str(trigger) + ']'
    else:
        # Ignorare altre frame termoregolazione non gestite.
        None
    return trigger, nzo, vt


#Routine per la gestione dell'energia
def gestioneEnergia(trigger):
    nto = 0
    vto = float(0.0)
    if trigger.split('*')[3] == '113':
        # Numero toroide
        nto = int(trigger.split('*')[2][-1])
        #print nto
        # Lettura dati energia
        vto = trigger.split('*')[4]
        vto = float(vto[:-2])
        #print vto
        # Trigger
        trigger = 'TE5' + str(nto)
        #print trigger
    elif (trigger.split('*')[3][:3]) == '511' and trigger.split('*')[4] == '25':
        # Numero toroide
        nto = int(trigger.split('*')[2][-1])
        #print nto
        # Lettura dati energia
        vto = fixener(trigger.split('*')[5])
        trigger = 'TE4' + str(nto)
        #print trigger
    elif trigger.split('*')[3][:2] == '52':
        # Numero toroide
        nto = int(trigger.split('*')[2][-1])
        #print nto
        # Lettura dati energia
        vto = fixener(trigger.split('*')[4])
        trigger = 'TE3' + str(nto)
        #print trigger
    elif trigger.split('*')[3] == '53':
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
    return trigger, nto, vto   
    

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
            logging.warn('Errore invio messaggio pushover a seguito di evento ' + trigger)
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
            logging.warn('Errore invio e-mail a ' + str(emldata[0]) + ' a seguito di evento ' + trigger)
    elif channel == 'BUS':
        # ***********************************************************
        # ** SCS-BUS channel                                       **
        # ***********************************************************
        busdata = data.split('|')
        if opencmd_service(busdata[0]) == True:
            logging.info('Eseguito/i comando/i OPEN preimpostato/i a seguito di evento ' + trigger)
        else:
            logging.warn('Errore esecuzione comando/i OPEN preimpostato/i a seguito di evento ' + trigger)
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
        

def pushover_service(pomsg):
    bOK = True
    try:
        # Lettura parametri Pushover da file di configurazione
        poat = ET.parse(CFGFILENAME).find("channels/channel[@type='POV']").attrib['api_token']
        pouk = ET.parse(CFGFILENAME).find("channels/channel[@type='POV']").attrib['user_key']
        poaddr = ET.parse(CFGFILENAME).find("channels/channel[@type='POV']").attrib['address']
        conn = httplib.HTTPSConnection(poaddr)
        conn.request("POST", "/1/messages.json",
          urllib.urlencode({
            "token": poat,
            "user": pouk,
            "message": pomsg,
          }), { "Content-type": "application/x-www-form-urlencoded" })
        conn.getresponse()
    except:
        bOK = False
    finally:
        return bOK


def batch_service(batchdata):
    bOK = True
    try:
        import subprocess
        # Determina tip osistema operativo
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
        serport = ET.parse(CFGFILENAME).find("channels/channel[@type='SMS']").attrib['serport']
        serspeed = ET.parse(CFGFILENAME).find("channels/channel[@type='SMS']").attrib['serspeed']
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
        # Lettura parametri Pushover da file di configurazione
        ckey = ET.parse(CFGFILENAME).find("channels/channel[@type='TWT']").attrib['ckey']
        cset = ET.parse(CFGFILENAME).find("channels/channel[@type='TWT']").attrib['csecret']
        atkey = ET.parse(CFGFILENAME).find("channels/channel[@type='TWT']").attrib['atkey']
        atsec = ET.parse(CFGFILENAME).find("channels/channel[@type='TWT']").attrib['atsecret']
        twdest = twtdest.split(';')
        if DEBUG == 1:
            print twdest
        # Instanziamento classe TwitterApi
        twtobj = TwitterApi(ckey,cset,atkey,atsec)
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
        # Lettura parametri e-mail da file di configurazione
        smtpsrv = ET.parse(CFGFILENAME).find("channels/channel[@type='EML']").attrib['smtp']
        smtpport = cset = ET.parse(CFGFILENAME).find("channels/channel[@type='EML']").attrib['smtp_port']
        smtpauth = ET.parse(CFGFILENAME).find("channels/channel[@type='EML']").attrib['smtp_auth']
        smtpuser = ET.parse(CFGFILENAME).find("channels/channel[@type='EML']").attrib['smtp_user']
        smtppsw = ET.parse(CFGFILENAME).find("channels/channel[@type='EML']").attrib['smtp_psw']
        smtptls = ET.parse(CFGFILENAME).find("channels/channel[@type='EML']").attrib['smtp_tls_sec']
        sender = ET.parse(CFGFILENAME).find("channels/channel[@type='EML']").attrib['sender']
        mailobj = EmailSender(smtpsrv,smtpport,smtpauth,smtpuser,smtppsw,smtptls,sender)
        if not mailobj.send_email(emldest,emlobj,emltext) == True:
            bOK = False
    except Exception, err:
        bOK = False
        print 'Errore in invio email! [' + str(sys.exc_info()) + ']'
    finally:
        return bOK


def opencmd_service(opencmd):
    bOK = True
    try:
        # Lettura parametri Pushover da file di configurazione
        mhgateway_ip = ET.parse(CFGFILENAME).find("gateways/gateway[@priority='1']").attrib['address']
        mhgateway_port = ET.parse(CFGFILENAME).find("gateways/gateway[@priority='1']").attrib['port']
        # Instanziamento classe MyHome
        mhobj = MyHome(mhgateway_ip,mhgateway_port)
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
    print 'scrivo ' + str(tidt)
    pickle.dump(tidt,open("tempdata.p", "wb"))

def fixener(vto):
   # Adatta il formato di energia
   vto = vto[:-2]
   vto = round(float(vto)/1000 , 2)
   #vto = vto/1000,2)
   #vto = str(vto)
   #vto = vto.replace(".",",")
   return vto

def ifttt_service(trigger,iftext):
    bOK = True
    try:
        # Lettura parametri IFT  da file di configurazione
        IFT_address = ET.parse(CFGFILENAME).find("channels/channel[@type='IFT']").attrib['address']
        if DEBUG == 1:
            print 'IFT_address: ' + IFT_address
	    ckey = ET.parse(CFGFILENAME).find("channels/channel[@type='IFT']").attrib['ckey']
        url = IFT_address.format(e=trigger,k=ckey)
        if DEBUG == 1:
            print 'IFT Preparazione= trigger: ' + trigger + ' ckey ' + ckey + ' url ' + url
        payload = {'value1': iftext}
        return requests.post(url, data=payload)
    except:
        bOK = False
    finally:
        return bOK

