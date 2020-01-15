import asyncio
import aiohttp
import os
import json
import webexteamssdk
import logging
import functools
import base64
from demobot import get_joke, traffic, number, dilbert, peanuts, quote
from concurrent.futures import ThreadPoolExecutor, Executor

from typing import Optional, Callable, List, Coroutine, Dict, Any, NoReturn

ALWAYS_USE_NEW_DEVICE = False  # if set all existing Bot devices will be deleted
WDM_DEVICES = 'https://wdm-a.wbx2.com/wdm/api/v1/devices'

log = logging.getLogger(__name__)

MessageCallback = Callable[[webexteamssdk.Message], Coroutine]


class BotSocket:
    """
    Bot helper based on Webex Teams device registration and Websocket
    """

    def __init__(self,
                 access_token: str,
                 device_name: Optional[str] = None,
                 default_action: Optional[str] = '/help',
                 executor: Optional[Executor] = None) -> None:
        self._token = access_token
        self._device_name = device_name or os.path.basename(os.path.splitext(__file__)[0])
        self._session: Optional[aiohttp.ClientSession] = None
        self._api = webexteamssdk.WebexTeamsAPI(access_token=access_token)
        self._commands = {
            "/echo": {
                "help": "Display help text.",
                "callback": self.send_echo,
            },
            "/help": {"help": "Get help.", "callback": self.send_help},
        }
        self._default_action = default_action
        self._executor = executor or ThreadPoolExecutor(max_workers=4)


@property
def auth(self) -> str:
    return f'Bearer {self._token}'


async def request(self, method: str,
                  url: str,
                  headers: Optional[Dict[str, str]] = None, **kwargs) -> Dict[str, Any]:
    headers = headers or dict()
    headers['Authorization'] = self.auth
    async with self._session.request(method=method, url=url, headers=headers, **kwargs) as r:
        r.raise_for_status()
        result = await r.json()
    return result


async def get(self, url: str, **kwargs) -> Dict[str, Any]:
    return await self.request(method='GET', url=url, **kwargs)


async def post(self, url: str, **kwargs) -> Dict[str, Any]:
    return await self.request(method='POST', url=url, **kwargs)


async def put(self, url: str, **kwargs) -> Dict[str, Any]:
    return await self.request(method='PUT', url=url, **kwargs)


async def delete(self, url: str, **kwargs) -> Dict[str, Any]:
    return await self.request(method='DELETE', url=url, **kwargs)


async def find_device(self) -> Optional[Dict[str, Any]]:
    """
    Get the WDM device list and return the device created by the bot (if any)
    :return: existing device or None
    """
    device = None
    try:
        r = await self.get(url=WDM_DEVICES)
        devices = r['devices']
        # there should only be one device!?
        if len(devices) > 1:
            log.warning(f'Found {len(devices)} devices: {", ".join(d["name"] for d in devices)}')
        if ALWAYS_USE_NEW_DEVICE or len(devices) > 1:
            log.debug(f'deleting {len(devices)} device(s)...')
            tasks = [self.delete(url=d['url']) for d in devices]
            r = await asyncio.gather(*tasks, return_exceptions=True)
            devices = []
        # get a device from the (potentially empty) list of devices
        device = next((d for d in devices if d['name'] == self._device_name), None)
        if device is not None:
            # update registration
            log.debug(f'Updating registration {device["url"]}')
            device = await self.put(url=device['url'], json=device)
    except aiohttp.ClientResponseError as e:
        e: aiohttp.ClientResponseError
        if e.status == 404:
            # api throws a 404 if no devices exist
            return None
        raise e
    return device


async def create_device(self) -> Dict[str, Any]:
    """
    create/register a new WDM device for the bot
    :return: device
    """
    device = dict(
        deviceName=f'{self._device_name}-client',
        deviceType='DESKTOP',
        localizedModel='python',
        model='python',
        name=f'{self._device_name}',
        systemName=f'{self._device_name}',
        systemVersion='0.1'
    )
    device = await self.post(url=WDM_DEVICES, json=device)
    log.debug(f'New device {device["url"]}')
    return device


async def get_message(self, message_id: str) -> Optional[webexteamssdk.Message]:
    """
    Get a message given a message id
    :param message_id: message id; can be a UUID or a Webex id (api is fine w/ both!)
    :return: obtained message or None
    """
    try:
        r = await self.get(url=f'https://api.ciscospark.com/v1/messages/{message_id}')
        return webexteamssdk.Message(r)
    except Exception as e:
        return None


def run(self) -> NoReturn:
    """
    Actually run the bot; never returns
    :return: never returns
    """

    def process(message: webexteamssdk.Message) -> None:
        """
        Get details of message references in a given activity and call the defined callback w/ the detailed message
        data
        this is run in a thread to avoid blocking asynchronous handling
        :param message: websocket message to process
        :param ignore_emails: list of emails to ignore
        """

        # Log details of message
        log.debug(f'process: message {message.id} from: {message.personEmail}')

        # Find the command that was sent, if any
        command = ""
        for c in self._commands.items():
            if message.text.find(c[0]) != -1:
                command = c[0]
                log.debug(f'Found command: {command}')
                # If a command was found, stop looking for others
                break

        # Build the reply to the user
        reply = None

        # Take action based on command
        # If no command found, send the default_action
        if command in [""] and self._default_action:
            reply = self._commands[self._default_action]["callback"](message)
        elif command in self._commands.keys():
            reply = self._commands[command]["callback"](message)
        else:
            pass

        # allow command handlers to craft their own Teams message
        if reply:
            self._api.messages.create(roomId=message.roomId, markdown=reply)
        log.debug(f'process: message {message.id} from: {message.personEmail} done')
        return

    async def get_message_and_process(message_id: str) -> None:
        """
        get an actual (unencrypted) message via the public API and process the message in a Thread
        :param message_id: message id
        :return: None
        """
        # get the actual (unencrypted) message via the public APIs
        # luckily we can actually pass a UUID to the public API as well :-)
        message = await self.get_message(message_id=message_id)
        if message is None:
            return

        # schedule execution of process(message)
        self._executor.submit(process, message)
        log.debug(f'scheduled processing of message: {message_id}, {message}')

    async def as_run() -> NoReturn:
        """
        find/create device registration and listen for messages on websocket. For posted messages a task is
        scheduled to call the configured callback with the details of the posted message. This call is executed
        in a thread so that blocking i/o in the callback does not block asynchronous handling of further messages
        received on the websocket
        """
        self._session = aiohttp.ClientSession()
        loop = asyncio.get_running_loop()
        while True:
            # find/create device registration
            device = await self.find_device()
            if device:
                log.debug('using existing device')
            else:
                log.debug('Creating new device')
                device = await self.create_device()

            # we need to ignore messages from our own email addresses
            me = await self.get(url='https://api.ciscospark.com/v1/people/me')
            ignore_emails = me['emails']

            wss_url = device['webSocketUrl']
            log.debug(f'WSS url: {wss_url}')
            async with self._session.ws_connect(url=wss_url, headers={'Authorization': self.auth}) as wss:
                async for message in wss:
                    log.debug(f'got message from websocket: {message}')

                    data = json.loads(message.data.decode('utf8'))
                    data = data['data']
                    if data['eventType'] != 'conversation.activity':
                        continue
                    activity = data['activity']
                    if activity['verb'] != 'post':
                        continue
                    if activity['actor']['emailAddress'] in ignore_emails:
                        log.debug(f'ignoring message from self')
                        continue

                    # create task to get message details and schedule processing
                    # we don't want to delay handling of messages on the websocket
                    message_id = activity['id']
                    loop.create_task(get_message_and_process(message_id=message_id))
                # async for
            # async with
        # while True

    # run async code
    asyncio.run(as_run())


def add_command(self, command, help_message, callback):
    """
    Add a new command to the bot
    :param command: The command string, example "/status"
    :param help_message: A Help string for this command
    :param callback: The function to run when this command is given
    :return:
    """
    self._commands[command] = {"help": help_message, "callback": callback}


def remove_command(self, command):
    """
    Remove a command from the bot
    :param command: The command string, example "/status"
    :return:
    """
    del self._commands[command]


def extract_message(self, command, text):
    """
    Return message contents following a given command.
    :param command: Command to search for.  Example "/echo"
    :param text: text to search within.
    :return:
    """
    cmd_loc = text.find(command)
    message = text[cmd_loc + len(command):]
    return message


def set_greeting(self, callback):
    """
    Configure the response provided by the bot when no command is found.
    :param callback: The function to run to create and return the greeting.
    :return:
    """
    self.add_command(
        command="/greeting", help_message="*", callback=callback
    )
    self.default_action = "/greeting"


# *** Default Commands included in Bot
def send_help(self, message):
    """
    Construct a help message for users.
    :param post_data:
    :return:
    """
    message = "Hello!  "
    message += "I understand the following commands:  \n"
    for c in self._commands.items():
        if c[1]["help"][0] != "*":
            message += "* **%s**: %s \n" % (c[0], c[1]["help"])
    return message


def send_echo(self, message: webexteamssdk.Message):
    """
    Sample command function that just echos back the sent message
    :param post_data:
    :return:
    """
    # Get sent message
    message = self.extract_message("/echo", message.text)
    return message


if __name__ == '__main__':
    with open('bot_access_token', 'r') as f:
        access_token = f.readline().strip()
    api = webexteamssdk.WebexTeamsAPI(access_token=access_token)

    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(threadName)s %(name)-12s %(levelname)-8s %(message)s')
    logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)
    logging.getLogger('asyncio').setLevel(logging.INFO)
    bot = BotSocket(access_token=access_token)
    bot.add_command('/chuck', 'get Chuck Norris joke', get_joke)
    bot.add_command('/traffic', 'show traffic cams', functools.partial(traffic, api))
    bot.add_command('/quote', 'get a random quote', quote)
    bot.add_command('/number', 'get fun fact for a number', functools.partial(number, api))
    bot.add_command('/dilbert', 'get random dilbert comic', functools.partial(dilbert, api))
    bot.add_command('/peanuts', 'get random peanuts comic', peanuts)
    bot.run()
