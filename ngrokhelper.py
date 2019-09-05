import threading
import shutil
import json
import requests
import time
import subprocess
import logging

log = logging.getLogger(__name__)

class NgrokHelper(threading.Thread):
    ''' Ngrok: class to automate starting a local ngrok instance as a subprocess.
    '''

    def __init__(self, port=None):
        '''Initalize Ngrok tunnel.

        :param port: int, localhost port forwarded through tunnel

        '''
        assert shutil.which("ngrok"), "ngrok command must be installed, see https://ngrok.com/"
        super(NgrokHelper, self).__init__()

        self.port = port
        return

    def read_json_from_ngrok(self):
        ''' read stdout of ngrok process and try to parse as JSON

            returns: decoded JSON of single ngrok output line
        '''
        while True:
            line = self.ngrok.stdout.readline().decode()
            # try to parse as JSON
            try:
                line = json.loads(line)
            except json.JSONDecodeError:
                # ignore anything that isn't JSON
                continue
            break
        return line

    def start(self):
        '''
        start a local ngrok process
        start a thread in the background to read stdout of the ngrok process
        As soon as the nrgok client connection has been established determine the public URL and report that back
        '''

        # where is ngrok?
        ngrok = shutil.which('ngrok')

        # commandline to start ngrok
        cmd = f'{ngrok} http {self.port} -log=stdout -log-format=json -log-level=info'

        # start ngrok process
        logging.debug(f'starting ngrok, command: {cmd}')
        self.ngrok = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE)

        # give it some time
        time.sleep(.5)
        assert self.ngrok.poll() is None, "ngrok failed to start"

        ngrok_addr = None
        log.info('Waiting for ngrok startup...')
        while True:
            line = self.read_json_from_ngrok()

            # {"addr":"127.0.0.1:4041","lvl":"info","msg":"starting web service","obj":"web","t":"2017-06-.."}
            if (line.get('obj') == 'web' and
                    line.get('lvl') == 'info' and
                    line.get('msg') == 'starting web service'):
                # get ngrok admin interface address from message
                ngrok_addr = line['addr']
                logging.debug(f'line: {line}')
                logging.debug(f'found address: {ngrok_addr}')
            # {"id":"44a534c2b867","lvl":"info","msg":"client session established","obj":"csess","t":"2017-06-.."}
            if (line.get('obj') == 'csess' and
                    line.get('lvl') == 'info'):
                # startup done: terminate loop
                logging.debug(f'line: {line}')
                logging.debug('Ngrok started')
                break

        # now as the ngrok client is up we can try to use the ngrok client API to get the public address of the tunnel
        # might take some time for the tunnels to come up; hence we try repeatedly until the API call succeeds

        ''' the expected JSON result looks something like this:
            {
                "tunnels": [
                    {
                        "proto": "https",
                        "name": "command_line",
                        "config": {
                            "addr": "localhost:60176",
                            "inspect": true
                        },
                        "metrics": {
                            ...
                        },
                        "public_url": "https://47bff724.ngrok.io",
                        "uri": "/api/tunnels/command_line"
                    },
                    {
                        "proto": "http",
                        "name": "command_line (http)",
                        "config": {
                            "addr": "localhost:60176",
                            "inspect": true
                        },
                        "metrics": {
                            ...
                        },
                        "public_url": "http://47bff724.ngrok.io",
                        "uri": "/api/tunnels/command_line+%28http%29"
                    }
                ],
                "uri": "/api/tunnels"
            }

        '''
        while True:
            log.info('Trying to get tunnel information from ngrok client API')
            response = requests.get('http://{}/api/tunnels'.format(ngrok_addr),
                                    headers={'content-type': 'application/json'}).json()
            logging.debug(f'Ngrok api response: {response}')
            if response.get('tunnels'):
                logging.debug('Got tunnel info')
                break
            time.sleep(0.5)

        # Default: take the 1st URL
        url = response['tunnels'][0]['public_url']

        # but we prefer HTTPS if an HTTPS tunnel exists
        https_tunnel = next((t for t in response['tunnels'] if t['proto'] == 'https'), None)
        if https_tunnel is not None:
            url = https_tunnel['public_url']

        # Now start the actual Thread
        threading.Thread.start(self)

        # return the public URL
        return url

    def stop(self):
        """Tell ngrok to tear down the tunnel.

        Stop the background tunneling process.
        """
        self.ngrok.terminate()
        return

    def run(self):
        # continuously read from the ngrok process output to prevent the process from blocking
        while True:
            line = self.read_json_from_ngrok()
            logging.debug(f'JSON message from ngrok: {line}')
        return