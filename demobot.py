from webexteamsbot import TeamsBot
import ngrokhelper
import requests
import requests_toolbelt
import webexteamssdk
import functools
import re
from bs4 import BeautifulSoup
import random
import logging
import urllib.parse
import flask
import json

bot_email = 'demo_jkrohn@webex.bot'
with open('bot_access_token', 'r') as f:
    teams_token = f.readline().strip()
bot_app_name = 'Demo Bot jkrohn'

"""
# Retrieve required details from environment variables
if False:
    bot_email = os.getenv('BOT_EMAIL')
    teams_token = os.getenv('BOT_ACCESS_TOKEN')
    bot_app_name = os.getenv('BOT_APP_NAME')
else:
    bot_email = os.getenv('DEMOBOT_EMAIL')
    teams_token = os.getenv('DEMOBOT_ACCESS_TOKEN')
    bot_app_name = os.getenv('DEMOBOT_NAME')
"""


def get_joke(message):
    # get a random Chuck Norris joke
    # r = requests.get('http://api.icndb.com/jokes/random', params = {'limitTo': '[nerdy]'})
    # params = {'firstName': 'Johannes', 'lastName': 'Krohn'}
    # r = requests.get('http://api.icndb.com/jokes/random', params=params)

    r = requests.get('http://api.icndb.com/jokes/random', params={'limitTo': '[nerdy]'})
    r = r.json()
    joke = r['value']['joke']
    return joke


def get_snarl_traffic_cam_image_url(camera_id):
    """
    Get the URL of a traffic cam image from http://victoria.snarl.com.au
    :param camera_id: camera id
    :return: url
    """
    # get page with traffic cam info
    url = 'http://victoria.snarl.com.au/cams/single/{}'.format(camera_id)
    r = requests.get(url)

    # parse page and extract image URL
    soup = BeautifulSoup(r.text, 'html.parser')
    try:
        img = soup.find('div', id='traffic-cam-details').find('img')
    except AttributeError:
        img = None
    if img is None:
        return None
    return img['src']


def traffic(api, message):
    """
    Act on the /traffic command. Post a few traffic cam images to a Cisco Spark space
    :param api: Spark API instance
    :param message: message object
    :return: markdown of text to be posted
    """

    # URLs of a few traffic cams in Germany
    german_traffic_cams = [
        'http://autobahn-rlp.de/syncdata/cam/380/thumb_640x480.jpg',
        'http://autobahn-rlp.de/syncdata/cam/385/thumb_640x480.jpg',
        'http://autobahn-rlp.de/syncdata/cam/165/thumb_640x480.jpg'
    ]

    # some camera IDs in Melbourne
    snarl_cam_ids = [105, 107, 142, 143]

    room_id = message.roomId

    # need to post the attachments individually as the Cisco Spark API currently only supports one attachment at a time.
    for file in german_traffic_cams:
        api.messages.create(roomId=room_id, files=[file])

    # get image URLs for the given camera IDs
    snarl_cam_urls = (get_snarl_traffic_cam_image_url(cam_id) for cam_id in snarl_cam_ids)

    # only take the actual URLs; ignore None instances
    snarl_cam_urls = (url for url in snarl_cam_urls if url is not None)

    # finally post all images to the space
    for cam_url in snarl_cam_urls:
        api.messages.create(roomId=room_id, files=[cam_url])

    return 'Traffic cam images posted above as requested'

def number(api, message):
    """
    Get a fun fact for a number
    """
    m = re.match(r'.*/number(\s+\d+)?', message.text)
    try:
        number = m.groups()[0]
        number = str(int(number))
    except (TypeError, ValueError, AttributeError):
        number = 'random'
        api.messages.create(roomId=message.roomId,
                            text='No number provided. Getting fun fact for a randum number.')

    r = requests.get('http://numbersapi.com/{number}'.format(number=number))
    return r.text


def dilbert(api, message):
    m = re.match(r'.*/dilbert\s+(\S+)?', message.text)
    try:
        search_param = m.groups()[0]
    except (TypeError, ValueError, AttributeError):
        search_param = None

    if search_param is None:
        search_param = 'management'

    search_url = 'https://dilbert.com/search_results?terms={search_param}'.format(search_param=search_param)
    r = requests.get(search_url)
    soup = BeautifulSoup(r.text, "html.parser")
    comics = soup.find_all('div', class_='comic-item-container')
    images = [urllib.parse.urljoin(search_url, c.attrs['data-image']) for c in comics]
    if not images:
        message = 'Sorry, couldn\'t find any Dilbert strip for your search term \'{search_param}\''.format(
            search_param=search_param)
    else:
        api.messages.create(roomId=message.roomId, files=[random.choice(images)])
        message = 'Here you go..'
    return message


def peanuts(message):
    """
    Get a random Peanuts comic from the Peanuts web page and post that comic to the space
    """
    s = requests.Session()
    url = 'https://www.peanuts.com/comics/'
    r = s.get(url=url)
    soup = BeautifulSoup(r.text, "html.parser")
    comics = soup.find_all('span', class_='peanuts-comic-strip')
    images = [c.img for c in comics]

    # each image has a list of urls in the srcset attribute
    # <img width="855" height="588" src="https://www.peanuts.com/wp-content/uploads/2017/09/pe080629comb_hs-855x588
    # .png" class="attachment-desktop-comic size-desktop-comic" alt=""
    # srcset="https://www.peanuts.com/wp-content/uploads/2017/09/pe080629comb_hs-855x588.png 855w,
    # https://www.peanuts.com/wp-content/uploads/2017/09/pe080629comb_hs-300x206.png 300w,
    # https://www.peanuts.com/wp-content/uploads/2017/09/pe080629comb_hs-768x528.png 768w,
    # https://www.peanuts.com/wp-content/uploads/2017/09/pe080629comb_hs-1024x704.png 1024w,
    # https://www.peanuts.com/wp-content/uploads/2017/09/pe080629comb_hs-675x464.png 675w" sizes="(max-width: 855px)
    # 100vw, 855px">
    src_sets = [i.get_attribute_list('srcset')[0] for i in images]

    # the urls are comma separated
    src_sets = [s.split(',') for s in src_sets]

    # each url entry is a space separated tuple of url and a width attribute
    # https://www.peanuts.com/wp-content/uploads/2017/09/pe080629comb_hs-1024x704.png 1024w
    src_sets = [list(map(lambda x: x.strip().split(' '), sl)) for sl in src_sets]
    src_sets = [{w: url for url, w in sl} for sl in src_sets]

    # we only want urls of 1024w images
    images = [sl.get('1024w') for sl in src_sets]
    images = [i for i in images if i is not None]

    if images:
        # we can't post the image using the reqular message.create call b/c the url obtained above only works if the
        # right cookie and a referer header is sent in the request. The Webex backend has no knowledge of this. Thus
        # the only way to make this work ist to get the image locally and then post the attachment using a multi-part
        # mime message
        image = random.choice(images)
        headers = dict(referer='https://www.peanuts.com/comics/')
        r = s.get(image, headers=headers)

        # prepare the multipart body
        data = {
            'roomId': message.roomId,
            'text': 'Here you go',
            'files': ('Image.png', r.content, r.headers['content-type'])
        }
        multi_part = requests_toolbelt.MultipartEncoder(fields=data)

        headers = {'Content-Type': multi_part.content_type,
                   'Authorization': 'Bearer {}'.format(teams_token)}

        r = requests.post('https://api.ciscospark.com/v1/messages', data=multi_part, headers=headers)
        message = 'How do you like that?'
    else:
        message = 'Sorry, couldn\'t find any Peanuts comics'

    return message

def card_demo(api, message):
    card_json = """{
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.0",
        "body": [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": "Input.Text elements",
                "horizontalAlignment": "Center"
            },
            {
                "type": "Input.Text",
                "placeholder": "Name",
                "style": "text",
                "maxLength": 0,
                "id": "SimpleVal"
            },
            {
                "type": "Input.Text",
                "placeholder": "Homepage",
                "style": "Url",
                "maxLength": 0,
                "id": "UrlVal"
            },
            {
                "type": "Input.Text",
                "placeholder": "Email",
                "style": "Email",
                "maxLength": 0,
                "id": "EmailVal"
            },
            {
                "type": "Input.Text",
                "placeholder": "Phone",
                "style": "Tel",
                "maxLength": 0,
                "id": "TelVal"
            },
            {
                "type": "Input.Text",
                "placeholder": "Comments",
                "style": "text",
                "isMultiline": true,
                "maxLength": 0,
                "id": "MultiLineVal"
            },
            {
                "type": "Input.Number",
                "placeholder": "Quantity",
                "min": -5,
                "max": 5,
                "id": "NumVal"
            },
            {
                "type": "Input.Date",
                "placeholder": "Due Date",
                "id": "DateVal",
                "value": "2017-09-20"
            },
            {
                "type": "Input.Time",
                "placeholder": "Start time",
                "id": "TimeVal",
                "value": "16:59"
            },
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": "Input.ChoiceSet",
                "horizontalAlignment": "Center"
            },
            {
                "type": "TextBlock",
                "text": "What color do you want? (compact)"
            },
            {
                "type": "Input.ChoiceSet",
                "id": "CompactSelectVal",
                "value": "1",
                "choices": [
                    {
                        "title": "Red",
                        "value": "1"
                    },
                    {
                        "title": "Green",
                        "value": "2"
                    },
                    {
                        "title": "Blue",
                        "value": "3"
                    }
                ]
            },
            {
                "type": "TextBlock",
                "text": "What color do you want? (expanded)"
            },
            {
                "type": "Input.ChoiceSet",
                "id": "SingleSelectVal",
                "style": "expanded",
                "value": "1",
                "choices": [
                    {
                        "title": "Red",
                        "value": "1"
                    },
                    {
                        "title": "Green",
                        "value": "2"
                    },
                    {
                        "title": "Blue",
                        "value": "3"
                    }
                ]
            },
            {
                "type": "TextBlock",
                "text": "What colors do you want? (multiselect)"
            },
            {
                "type": "Input.ChoiceSet",
                "id": "MultiSelectVal",
                "isMultiSelect": true,
                "value": "1,3",
                "choices": [
                    {
                        "title": "Red",
                        "value": "1"
                    },
                    {
                        "title": "Green",
                        "value": "2"
                    },
                    {
                        "title": "Blue",
                        "value": "3"
                    }
                ]
            },
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": "Input.Toggle",
                "horizontalAlignment": "Center"
            },
            {
                "type": "Input.Toggle",
                "title": "I accept the terms and conditions (True/False)",
                "id": "AcceptsTerms",
                "value": "false",
                "wrap": false
            },
            {
                "type": "Input.Toggle",
                "title": "Red cars are better than other cars",
                "valueOn": "RedCars",
                "valueOff": "NotRedCars",
                "id": "ColorPreference",
                "value": "NotRedCars",
                "wrap": false
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Submit",
                "data": {
                    "id": "1234567890"
                }
            },
            {
                "type": "Action.ShowCard",
                "title": "Show Card",
                "card": {
                    "type": "AdaptiveCard",
                    "body": [
                        {
                            "type": "Input.Text",
                            "placeholder": "enter comment",
                            "style": "text",
                            "maxLength": 0,
                            "id": "CommentVal"
                        }
                    ],
                    "actions": [
                        {
                            "type": "Action.Submit",
                            "title": "OK"
                        }
                    ],
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json"
                }
            }
        ]
    }"""
    card_json=json.loads(card_json)
    data = {
        'roomId': message.roomId,
        'text': 'simple adaptive card demo',
        'fallbackText': 'this is an adaptive card demo. Too bad your app does not support this',
        'attachments': [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card_json
            }
        ]
    }
    headers = {'Authorization': f'Bearer {teams_token}'}
    r = requests.post('https://api.ciscospark.com/v1/messages', json=data, headers=headers)
    return ''
    pass

def card_action(api):
    """
    registered endpoint in Flask for the card action webhook
    """
    request = flask.request.json
    attachment_id = request['data']['id']

    # get the attachment
    headers = {'Authorization': f'Bearer {teams_token}'}
    r = requests.get(f'https://api.ciscospark.com/v1/attachment/actions/{attachment_id}', headers=headers)
    r.raise_for_status()
    action = r.json()
    inputs = '\n'.join(f'{k}={v}' for k,v in action['inputs'].items())
    text = 'Here is what i got:\n\n'
    text = f'{text}{inputs}'
    api.messages.create(roomId=action['roomId'], text = text)
    return 'ok'

def main():
    logging.basicConfig(level=logging.DEBUG)

    ngrok = ngrokhelper.NgrokHelper(port=5000)
    bot_url = ngrok.start()

    logging.debug(f'Bot url: {bot_url}')

    # Create a new bot
    bot = TeamsBot(bot_app_name, teams_bot_token=teams_token,
                   teams_bot_url=bot_url, teams_bot_email=bot_email, debug=True)

    # Spark API
    api = webexteamssdk.WebexTeamsAPI(teams_token)

    # for the adaptive card demo we also need a webhook for card actions
    url = urllib.parse.urljoin(bot_url, 'card_action')
    name = f'{bot_app_name}_card_action'
    wh = next((h for h in api.webhooks.list() if h.name==name), None)
    if wh is None:
        # create new webhook for card activities
        api.webhooks.create(name=name, targetUrl=url, resource='attachmentActions', event='created')
    else:
        # update existing webhook
        api.webhooks.update(webhookId=wh.id, name=name, targetUrl=url, resource='attachmentActions', event='created')

    # register code for that webhook
    bot.add_url_rule('/card_action', 'card_action', functools.partial(card_action, api), methods=['POST'])

    # Add new command
    bot.add_command('/chuck', 'get Chuck Norris joke', get_joke)
    bot.add_command('/traffic', 'show traffic cams', functools.partial(traffic, api))
    bot.add_command('/number', 'get fun fact for a number', functools.partial(number, api))
    bot.add_command('/dilbert', 'get random dilbert comic', functools.partial(dilbert, api))
    bot.add_command('/peanuts', 'get random peanuts comic', peanuts)
    bot.add_command('/card', 'create an adaptive card', functools.partial(card_demo, api))

    # run bot
    bot.run(host='0.0.0.0', port=5000)


if __name__ == '__main__':
    main()
