from WMCore.Services.UserFileCache.UserFileCache  import UserFileCache
from CRABClient.Commands.SubCommand import SubCommand
from CRABClient.ClientUtilities import colors, server_info, getUrl
from CRABClient.ClientExceptions import ConfigurationException, ConfigException, RESTCommunicationException
from httplib import HTTPException
import CRABClient.Emulator
from CRABClient import __version__

import glob
import subprocess

class purge(SubCommand):
    """
    clean user schedd and cache for a given task. User must specify the taskname to be purge
    """

    visible = True

    def __call__(self):

        self.logger.info('Getting the tarball hash key')

        tarballdir = glob.glob(self.requestarea+'/inputs/*.tgz')
        if len(tarballdir) != 1:
            self.logger.info('%sError%s: Could not find tarball or there is more than one tarball'% (colors.RED, colors.NORMAL))
            raise ConfigurationException
        tarballdir = tarballdir[0]

        #checking task status

        self.logger.info('Checking task status')
        serverFactory = CRABClient.Emulator.getEmulator('rest')
        server = serverFactory(self.serverurl, self.proxyfilename, self.proxyfilename, version=__version__)
        dictresult, status, _ = server.get(self.uri, data = {'workflow': self.cachedinfo['RequestName'], 'verbose': 0})

        dictresult = dictresult['result'][0] #take just the significant part

        if status != 200:
            msg = "Problem retrieving task status:\ninput: %s\noutput: %s\nreason: %s" % (str(self.cachedinfo['RequestName']), str(dictresult), str(reason))
            raise RESTCommunicationException(msg)

        self.logger.info('Task status: %s' % dictresult['status'])
        accepstate = ['KILLED','FINISHED','FAILED','KILLFAILED', 'COMPLETED']
        if dictresult['status'] not in accepstate:
            msg = ('%sError%s: Only tasks with these status can be purged: {0}'.format(accepstate) % (colors.RED, colors.NORMAL))
            raise ConfigurationException(msg)

        #getting the cache url
        cacheresult = {}
        scheddresult = {}
        gsisshdict = {}
        if not self.options.scheddonly:
            baseurl = getUrl(self.instance, resource='info')
            cacheurl = server_info('backendurls', self.serverurl, self.proxyfilename, baseurl)
            cacheurl = cacheurl['cacheSSL']
            cacheurldict = {'endpoint': cacheurl, 'pycurl': True}

            ufc = UserFileCache(cacheurldict)
            hashkey = ufc.checksum(tarballdir)
            self.logger.info('Tarball hashkey: %s' %hashkey)
            self.logger.info('Attempting to remove task file from crab server cache')

            try:
                ufcresult = ufc.removeFile(hashkey)
            except HTTPException, re:
                if re.headers.has_key('X-Error-Info') and 'Not such file' in re.headers['X-Error-Info']:
                    self.logger.info('%sError%s: Failed to find task file in crab server cache; the file might have been already purged' % (colors.RED,colors.NORMAL))
                    raise HTTPException , re

            if ufcresult == '':
                self.logger.info('%sSuccess%s: Successfully removed task files from crab server cache' % (colors.GREEN, colors.NORMAL))
                cacheresult = 'SUCCESS'
            else:
                self.logger.info('%sError%s: Failed to remove task files from crab server cache' % (colors.RED, colors.NORMAL))
                cacheresult = 'FAILED'

        if not self.options.cacheonly:
            self.logger.info('Getting schedd address')
            baseurl=self.getUrl(self.instance, resource='info')
            try:
                scheddaddress = server_info('scheddaddress', self.serverurl, self.proxyfilename, baseurl, workflow = self.cachedinfo['RequestName'] )
            except HTTPException, he:
                self.logger.info('%sError%s: Failed to get schedd address' % (colors.RED, colors.NORMAL))
                raise HTTPException,he
            self.logger.debug('%sSuccess%s: Successfully got schedd address' % (colors.GREEN, colors.NORMAL))
            self.logger.debug('Schedd address: %s' % scheddaddress)
            self.logger.info('Attempting to remove task from schedd')

            gssishrm = 'gsissh -o ConnectTimeout=60 -o PasswordAuthentication=no ' + scheddaddress + ' rm -rf ' + self.cachedinfo['RequestName']
            self.logger.debug('gsissh command: %s' % gssishrm)

            delprocess=subprocess.Popen(gssishrm, stdout= subprocess.PIPE, stderr= subprocess.PIPE, shell=True)
            stdout, stderr = delprocess.communicate()
            exitcode = delprocess.returncode

            if exitcode == 0 :
                self.logger.info('%sSuccess%s: Successfully removed task from scehdd' % (colors.GREEN, colors.NORMAL))
                scheddresult = 'SUCCESS'
                gsisshdict = {}
            else :
                self.logger.info('%sError%s: Failed to remove task from schedd' % (colors.RED, colors.NORMAL))
                scheddaddress = 'FAILED'
                self.logger.debug('gsissh stdout: %s\ngsissh stderr: %s\ngsissh exitcode: %s' % (stdout,stderr,exitcode))
                gsisshdict = {'stdout' : stdout, 'stderr' : stderr , 'exitcode' : exitcode}

            return {'cacheresult' : cacheresult , 'scheddresult' : scheddresult , 'gsiresult' : gsisshdict}


    def setOptions(self):
        """
        __setOptions__

        This allows to set specific command options
        """

        self.parser.add_option('--schedd',
                               dest = 'scheddonly',
                               action = 'store_true',
                               default = False,
                               help = 'Only clean schedd for the given workflow.')

        self.parser.add_option('--cache',
                               dest = 'cacheonly',
                               action = 'store_true',
                               default = False,
                               help = 'Only clean crab server cache for the given workflow.')

    def validateOptions(self):
        SubCommand.validateOptions(self)

        if self.options.scheddonly and self.options.cacheonly:
           self.logger.info('Options --schedd and --cache can not be specified simultaneously. No purging will be done.')
           raise ConfigException
