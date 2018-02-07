
import xml.etree.ElementTree as ET

CFGFILENAME = 'mhblconf.xml'  # Configuration file name
ALLXML_FILE = ET.parse(CFGFILENAME)    

def init():
    #ALLXML_FILE.iterfind("alerts/alert[@trigger='%s']" % (trigger)):
    #elem.attrib('data'),elem.attrib('channel'), elem.attrib('trigger')
    global alertElement
    alertElement = {} 
    for elem in ALLXML_FILE.iterfind("alerts/alert"):
        alertElement[elem.attrib['trigger']] =  elem 
        
    global enabledChannel
    enabledChannel = {}
    for elem in ALLXML_FILE.iterfind("channels/channel"):
        if elem.attrib['enabled'] == 'Y':
            enabledChannel[elem.attrib['type']] = 1
    
    global elencoSondeTemp
    elencoSondeTemp = {}
    for sonda in ALLXML_FILE.find("sondeTemp/sonda"):
        elencoSondeTemp[sonda.attrib['type']] = sonda
    
    # Lettura parametri TWITTER da file di configurazione
    global twt_ckey, twt_cset, twt_atkey, twt_atsec
    twt_ckey = ALLXML_FILE.find("channels/channel[@type='TWT']").attrib['ckey']
    twt_cset = ALLXML_FILE.find("channels/channel[@type='TWT']").attrib['csecret']
    twt_atkey = ALLXML_FILE.find("channels/channel[@type='TWT']").attrib['atkey']
    twt_atsec = ALLXML_FILE.find("channels/channel[@type='TWT']").attrib['atsecret']
    
    # Lettura parametri Pushover da file di configurazione
    global pov_poat, pov_pouk, pov_poaddr
    pov_poat = ALLXML_FILE.find("channels/channel[@type='POV']").attrib['api_token']
    pov_pouk = ALLXML_FILE.find("channels/channel[@type='POV']").attrib['user_key']
    pov_poaddr = ALLXML_FILE.find("channels/channel[@type='POV']").attrib['address']
    
    # Lettura parametri e-mail da file di configurazione
    global em_smtpsrv, em_smtpport, em_smtpauth, em_smtpuser, em_smtppsw, em_smtptls, em_sender
    em_smtpsrv = ALLXML_FILE.find("channels/channel[@type='EML']").attrib['smtp']
    em_smtpport = cset = ALLXML_FILE.find("channels/channel[@type='EML']").attrib['smtp_port']
    em_smtpauth = ALLXML_FILE.find("channels/channel[@type='EML']").attrib['smtp_auth']
    em_smtpuser = ALLXML_FILE.find("channels/channel[@type='EML']").attrib['smtp_user']
    em_smtppsw = ALLXML_FILE.find("channels/channel[@type='EML']").attrib['smtp_psw']
    em_smtptls = ALLXML_FILE.find("channels/channel[@type='EML']").attrib['smtp_tls_sec']
    em_sender = ALLXML_FILE.find("channels/channel[@type='EML']").attrib['sender']
    
    # Lettura parametri IFT  da file di configurazione
    global ift_address, ift_ckey
    ift_address = ALLXML_FILE.find("channels/channel[@type='IFT']").attrib['address']
    ift_ckey = ALLXML_FILE.find("channels/channel[@type='IFT']").attrib['ckey']
        
    # Lettura parametri gateway da file di configurazione
    global mhgateway_ip, mhgateway_port
    mhgateway_ip = ALLXML_FILE.find("gateways/gateway[@priority='1']").attrib['address']
    mhgateway_port = ALLXML_FILE.find("gateways/gateway[@priority='1']").attrib['port']
    
    #cfg_sonda = ALLXML_FILE.find("sondeTemp/sonda[@type='%s']") % (str(nzo))
    #statusChannel = ALLXML_FILE.find("channels/channel[@type='%s']").attrib['enabled'] % (channel)