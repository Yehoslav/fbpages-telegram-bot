# coding=utf-8
import json  # Used for tacking last dates
import logging  # Used for logging
import os
import sys  # Used for exiting the program
from datetime import datetime  # Used for date comparison

import telegram  # telegram-bot-python
from telegram.ext import Updater
from telegram.error import TelegramError, InvalidToken, BadRequest, TimedOut  # Error handling

import facebook  # facebook-sdk
import youtube_dl  # youtube-dl

# Logging
FMT = "[{asctime} {levelname:^9}] {name}: {message}"
FORMATS = {
    logging.DEBUG: FMT,
    logging.INFO: f'\33[36m{FMT}\33[0m',
    logging.WARNING: f'\33[33m{FMT}\33[0m',
    logging.ERROR: f'\33[31m{FMT}\33[0m',
    logging.CRITICAL: f'\33[1m\33[31m{FMT}\33[0m',
}


class CustomFormatter(logging.Formatter):
    def format(self, record):
        log_fmt = FORMATS[record.levelno]
        formatter = logging.Formatter(log_fmt, style='{')
        return formatter.format(record)


handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[handler])
logger = logging.getLogger(__name__)

# Global Variables
# TODO: Remove the global variables that don't really need to be global

# youtube-dl
ydl = youtube_dl.YoutubeDL({'outtmpl': '%(id)s%(ext)s'})

settings = {}
GRAPH: facebook.GraphAPI
BOT: telegram.Bot


def loadSettings() -> tuple:
    """
    Gets the needed settings from the environment variables.

    Returns: a tuple containing telegram_token, facebook_token, admin_id, and channel_id
    """

    # Load config
    try:
        admin_id = os.environ['ADMIN']
        channel_id = os.environ['CHANNEL']
        telegram_token = os.environ['TG_TOKEN']
        facebook_token = os.environ['FB_TOKEN']

    except KeyError:
        logger.critical("Environment variable not found")
        sys.exit('Tokens and ids not found')

    return telegram_token, facebook_token, admin_id, channel_id


def loadFacebookGraph(facebook_token):
    """
    Initialize Facebook GraphAPI with the token loaded from the settings file

    Args:
        facebook_token (str): The token needed to access the Facebook GraphAPI.
    """
    global GRAPH
    # TODO: Load facebook in the main function, why separately?
    GRAPH = facebook.GraphAPI(access_token=facebook_token, version='2.7')


def loadTelegramBot(telegram_token):
    """
    Initialize Telegram Bot API with the token loaded from the settings file
    """
    global BOT

    try:
        BOT = telegram.Bot(token=telegram_token)
    except InvalidToken:
        sys.exit('Fatal Error: Invalid Telegram Token')


def parsePostDate(post):
    """
    Converts 'created_time' str from a Facebook post to the 'datetime' format
    """
    date_format = "%Y-%m-%dT%H:%M:%S+0000"
    post_date = datetime.strptime(post['created_time'], date_format)
    return post_date


# noinspection PyPep8Naming
class dateTimeEncoder(json.JSONEncoder):
    """
    Converts the 'datetime' type to an ISO timestamp for the JSON dumper
    """

    def default(self, o):
        if isinstance(o, datetime):
            serial = o.isoformat()  # Save in ISO format
            return serial

        raise TypeError('Unknown type')


def dateTimeDecoder(pairs, date_format="%Y-%m-%dT%H:%M:%S"):
    """
    Converts the ISO timestamp to 'datetime' type for the JSON loader
    """
    d = {}

    for k, v in pairs:
        if isinstance(v, str):
            try:
                d[k] = datetime.strptime(v, date_format)
            except ValueError:
                d[k] = v
        else:
            d[k] = v

    return d


def loadDatesJSON(last_posts_dates, filename):
    """
    Loads the .json file containing the latest post's date for every page
    loaded from the settings file to the 'last_posts_dates' dict
    """
    with open(filename, 'r') as f:
        loaded_json = json.load(f, object_pairs_hook=dateTimeDecoder)

    print('Loaded JSON file.')
    return loaded_json


def dumpDatesJSON(last_posts_dates, filename):
    """
    Dumps the 'last_posts_dates' dict to a .json file containing the
    latest post's date for every page loaded from the settings file.
    """
    with open(filename, 'w') as f:
        json.dump(last_posts_dates, f,
                  sort_keys=True, indent=4, cls=dateTimeEncoder)

    print('Dumped JSON file.')
    return True


def getMostRecentPostsDates(facebook_pages, filename):
    """
    Gets the date for the most recent post for every page loaded from the
    settings file. If there is a 'dates.json' file, load it. If not, fetch
    the dates from Facebook and store them in the 'dates.json' file.
    The .json file is used to keep track of the latest posts posted to
    Telegram in case the bot is restarted after being down for a while.
    """
    print('Getting most recent posts dates...')

    # TODO: Remove the function, the bot will only run on feed update (at least so is the plan)

    global start_time
    global last_posts_dates

    last_posts = GRAPH.get_objects(
        ids=facebook_pages,
        fields='name,posts.limit(1){created_time}')

    print('Trying to load JSON file...')

    try:
        last_posts_dates = loadDatesJSON(last_posts_dates, filename)

        for page in facebook_pages:
            if page not in last_posts_dates:
                print('Checking if page ' + page + ' went online...')

                try:
                    last_post = last_posts[page]['posts']['data'][0]
                    last_posts_dates[page] = parsePostDate(last_post)
                    print('Page: ' + last_posts[page]['name'] + ' went online.')
                    dumpDatesJSON(last_posts_dates, filename)
                except KeyError:
                    print('Page ' + page + ' not found.')

        start_time = 0.0  # Makes the job run its callback function immediately

    except (IOError, ValueError):
        print('JSON file not found or corrupted, fetching latest dates...')

        for page in facebook_pages:
            try:
                last_post = last_posts[page]['posts']['data'][0]
                last_posts_dates[page] = parsePostDate(last_post)
                print('Checked page: ' + last_posts[page]['name'])
            except KeyError:
                print('Page ' + page + ' not found.')

        dumpDatesJSON(last_posts_dates, filename)


def getDirectURLVideo(video_id):
    """
    Get direct URL for the video using GraphAPI and the post's 'object_id'
    """
    print('Getting direct URL...')
    video_post = GRAPH.get_object(
        id=video_id,
        fields='source')

    return video_post['source']


def getDirectURLVideoYDL(URL):
    """
    Get direct URL for the video using youtube-dl
    """
    try:
        with ydl:
            result = ydl.extract_info(URL, download=False)  # Just get the link

        # Check if it's a playlist
        if 'entries' in result:
            video = result['entries'][0]
        else:
            video = result

        return video['url']
    except youtube_dl.utils.DownloadError:
        print('youtube-dl failed to parse URL.')
        return None


def postPhotoToChat(post, post_message, bot, chat_id):
    """
    Posts the post's picture with the appropriate caption.
    """
    direct_link = post['full_picture']

    try:
        message = bot.send_photo(
            chat_id=chat_id,
            photo=direct_link,
            caption=post_message)
        return message

    except (BadRequest, TimedOut):
        """If the picture can't be sent using its URL,
        it is downloaded locally and uploaded to Telegram."""
        print('Could not send photo file, sending link...')
        message = bot.send_message(  # Send direct link as a message
            chat_id=chat_id,
            text=direct_link + '\n' + post_message)
        return message


def postVideoToChat(post, post_message, bot, chat_id):
    """
    This function tries to pass 3 different URLs to the Telegram API
    instead of downloading the video file locally to save bandwidth.

    *First option":  Direct video source
    *Second option": Direct video source from youtube-dl
    *Third option":  Direct video source with smaller resolution
    "Fourth option": Download file locally for upload
    "Fifth option":  Send the video link
    """
    # If youtube link, post the link
    if 'caption' in post and post['caption'] == 'youtube.com':
        print('Sending YouTube link...')
        bot.send_message(
            chat_id=chat_id,
            text=post['link'])
    else:
        if 'object_id' in post:
            direct_link = getDirectURLVideo(post['object_id'])

        try:
            message = bot.send_video(
                chat_id=chat_id,
                video=direct_link,
                caption=post_message)
            return message

        except TelegramError:  # If the API can't send the video
            try:
                print('Could not post video, trying youtube-dl...')
                message = bot.send_video(
                    chat_id=chat_id,
                    video=getDirectURLVideoYDL(post['link']),
                    caption=post_message)
                return message

            except TelegramError:
                try:
                    print('Could not post video, trying smaller res...')
                    message = bot.send_video(
                        chat_id=chat_id,
                        video=post['source'],
                        caption=post_message)
                    return message

                except TelegramError:  # If it still can't send the video
                    print('Could not post video, sending link...')
                    message = bot.send_message(  # Send direct link as message
                        chat_id=chat_id,
                        text=direct_link + '\n' + post_message)
                    return message


def postLinkToChat(post, post_message, bot, chat_id):
    """
    Checks if the post has a message with its link in it. If it does,
    it sends only the message. If not, it sends the link followed by the
    post's message.
    """
    if post['link'] in post_message:
        post_link = ''
    else:
        post_link = post['link']

    bot.send_message(
        chat_id=chat_id,
        text=post_link + '\n' + post_message)


def postNewPost(post, bot, chat_id) -> bool:
    """
    Checks the type of the Facebook post and if it's allowed by the
    settings file, then calls the appropriate function for each type.
    """
    # If it's a shared post, call this function for the parent post
    if 'parent_id' in post and settings['allow_shared']:
        print('This is a shared post.')
        parent_post = GRAPH.get_object(
            id=post['parent_id'],
            fields='created_time,type,message,full_picture,story,\
                    source,link,caption,parent_id,object_id',
            locale=settings['locale'])
        print('Accessing parent post...')
        postNewPost(parent_post, bot, chat_id)
        return True

    """If there's a message in the post, and it's allowed by the
    settings file, store it in 'post_message', which will be passed to
    another function based on the post type."""
    if 'message' in post and settings['allow_message']:
        post_message = post['message']
    else:
        post_message = ''

    # Telegram doesn't allow media captions with more than 200 characters
    # Send separate message with the post's message
    if (len(post_message) > 200) and \
            (post['type'] == 'photo' or post['type'] == 'video'):
        separate_message = post_message
        post_message = ''
        send_separate = True
    else:
        separate_message = ''
        send_separate = False

    if post['type'] == 'photo' and settings['allow_photo']:
        print('Posting photo...')
        media_message = postPhotoToChat(post, post_message, bot, chat_id)
        if send_separate:
            media_message.reply_text(separate_message)
        return True
    elif post['type'] == 'video' and settings['allow_video']:
        print('Posting video...')
        media_message = postVideoToChat(post, post_message, bot, chat_id)
        if send_separate:
            media_message.reply_text(separate_message)
        return True
    elif post['type'] == 'status' and settings['allow_status']:
        print('Posting status...')
        try:
            bot.send_message(
                chat_id=chat_id,
                text=post['message'])
            return True
        except KeyError:
            print('Message not found, posting story...')
            bot.send_message(
                chat_id=chat_id,
                text=post['story'])
            return True
    elif post['type'] == 'link' and settings['allow_link']:
        print('Posting link...')
        postLinkToChat(post, post_message, bot, chat_id)
        return True
    else:
        print('This post is a {}, skipping...'.format(post['type']))
        return False


def periodicCheck(bot, new_post_id: str, chat_id: str, admin_id: str):
    """
    Checks for new posts for every page in the list loaded from the
    settings file, posts them, and updates the dates.json file, which
    contains the date for the latest post posted to Telegram for every
    page.
    """
    logger.info('Accessing Facebook...')

    try:
        # Request to the GraphAPI with all the pages (list) and required fields
        new_post_dict = GRAPH.get_object(
            id=new_post_id,
            fields='name,\
                    feed{\
                          created_time,type,message,full_picture,story,\
                          source,link,caption,parent_id,object_id}')

        # If there is an admin chat ID in the settings file
        if admin_id is not None:
            try:
                # Sends a message to the bot Admin confirming the action
                bot.send_message(
                    chat_id=admin_id,
                    text='Successfully fetched Facebook posts.')
            except TelegramError:
                logger.warning('Admin ID not found.')
                logger.info('Successfully fetched Facebook posts.')
        else:
            logger.info('Successfully fetched Facebook posts.')

    # Error in the Facebook API
    except facebook.GraphAPIError:
        logger.error('Error: Could not get Facebook posts.')
        """
        TODO: 'get_object' for every page individually, due to a bug
        in the Graph API that makes some pages return an OAuthException 1,
        which in turn doesn't allow the 'get_objects' method return a dict
        that has only the working pages, which is the expected behavior
        when one or more pages in 'facbeook_pages' are offline. One possible
        workaround is to create an Extended Page Access Token instad of an
        App Token, with the downside of having to renew it every two months.
        """
        return

    logger.info('The post was successfully retrieved, let\'s post it')


    if postNewPost(new_post_dict, chat_id):
        logger.info('Posted the post')
    else:
        logger.critical('Some error occurred while posting the posts.')


def error(bot, update, error):
    logger.warning('Update "{}" caused error "{}"'.format(update, error))


def main(new_post_id: str):
    global GRAPH

    telegram_token, facebook_token, admin_id, channel_id = loadSettings()
    GRAPH = facebook.GraphAPI(access_token=facebook_token, version='2.7')
    try:
        bot = telegram.Bot(token=telegram_token)
    except InvalidToken:
        sys.exit('Fatal Error: Invalid Telegram Token')

    # TODO: Rename the function
    periodicCheck(bot, new_post_id, channel_id, admin_id)

    # Log all errors
    updater = Updater(token=telegram_token)
    dispatcher = updater.dispatcher
    dispatcher.add_error_handler(error)

    # For now the bot will not be interactive, it will just look for new posts when the server is called.
    # updater.start_polling()
    # updater.idle()


if __name__ == '__main__':
    main()
