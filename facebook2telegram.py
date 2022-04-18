# coding=utf-8
import logging  # Used for logging
import os
from typing import Optional
import json

import telegram  # telegram-bot-python
from telegram.ext import Updater
from telegram.error import TelegramError, InvalidToken, BadRequest, TimedOut  # Error handling

from flask import Flask
import facebook  # facebook-sdk

server = Flask(__name__)

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
# handler.setFormatter(CustomFormatter())
logging.basicConfig(
    level=logging.WARNING,
    handlers=[handler],
    # filename='facebook2telegram.log'
)
logger = logging.getLogger(__name__)

ADMIN: int


class Post:

    def __init__(self, post: dict):
        self.post_id = post['id'] if 'id' in post else None
        self.message = post['message'] if 'message' in post else ''
        self.type = post['type'] if 'type' in post else None
        self.permalink: str = post['permalink_url'] if 'permalink_url' in post else None
        self.post_id = post['id'] if 'id' in post else None
        self.caption = post['caption'] if 'caption' in post else None

        if self.type == 'status':
            if 'attachments' in post:
                if post['attachments']['data'][0]['type'] == 'file_upload':
                    self.type = 'file_upload'
                    self.media_src = post['attachments']['data'][0]['url']
                else:
                    self.media_src = post['attachments']['data'][0]['media']['image']['src']
            else:
                self.media_src = None

        if self.type == 'link':
            if 'attachments' in post:
                self.type = 'share'
                self.media_src = post['attachments']['data'][0]['url']

        elif self.type == 'photo':
            self.media_src = post['attachments']['data'][0]['media']['image']['src']

        elif self.type == 'video':
            if self.caption == "youtube.com":
                self.media_src = post['attachments']['data'][0]['media']['source']
            else:
                self.media_src = post['attachments']['data'][0]['url']


def with_caption(func):
    def wrapper(
            bot: telegram.Bot,
            post: Post,
            chat_id,
    ) -> telegram.Message:
        if len(post.message) > 200:
            separate_message = post.message
            post.message = ''
            send_separate = True
        else:
            separate_message = ''
            send_separate = False

        message: Optional[telegram.Message]
        message = func(bot, post, chat_id)

        if send_separate and message is not None:
            message = message.reply_text(text=separate_message, quote=True)
        elif send_separate and message is None:
            message = bot.send_message(chat_id, text=separate_message + f'\n[link direct]({post.media_src})',
                                       parse_mode='Markdown')
        elif message is None:
            message = bot.send_message(chat_id, text=post.message + f'\n[media]({post.media_src})',
                                       parse_mode='Markdown')

        return message
    return wrapper


@with_caption
def postPhotoToChat(
        bot: telegram.Bot,
        post: Post,
        chat_id: str,
) -> Optional[telegram.Message]:
    """
    Posts the post's picture with the appropriate caption.
    """
    try:
        message = bot.send_photo(
            chat_id=chat_id,
            photo=post.media_src,
            caption=post.message)
        return message
    except BadRequest as e:
        bot.send_message(ADMIN, text=f'Could not send the photo.\n {e}')
        return None


def getDirectURLVideoYDL(url) -> str:
    """Get direct URL for the video"""
    return f"youtube.com/watch?v={url.split('?')[0].split('/')[-1]}"


def getDirectURLVideoFB(url) -> str:
    """Get direct URL for the video"""
    return f"facebook.com/watch/?v={url.split('/')[-2]}"


@with_caption
def postVideoToChat(bot: telegram.Bot, post: Post, chat_id: str)\
        -> Optional:
    """
    This function tries to pass 3 different URLs to the Telegram API
    instead of downloading the video file locally to save bandwidth.
    """

    try:
        logger.info('Post video...')
        message = bot.send_video(
            chat_id=chat_id,
            video=post.media_src)
        return message

    except TelegramError as e:  # If the API can't send the video
        try:
            if 'youtube.com' in post.media_src:
                logger.info('Sending YouTube link...')
                message = bot.send_message(
                    chat_id=chat_id,
                    text=f"{post.message}\n{getDirectURLVideoYDL(post.media_src)}")
                return message

            elif 'facebook.com' in post.media_src:
                logger.info('Sending Facebook Directlink...')
                message = bot.send_message(
                    chat_id=chat_id,
                    text=f"{post.message}\n{getDirectURLVideoFB(post.media_src)}")
                return message
        except TelegramError as e:
            bot.send_message(
                chat_id=ADMIN,
                text=e)
            return None

        logger.warning('Could not send the video. Posting just the message and the link to the post.')
        bot.send_message(
            chat_id=ADMIN,
            text=str(e))
        return None


def postSharedToChat(
        bot: telegram.Bot,
        post: Post,
        chat_id: str,
) -> telegram.Message:
    logger.info('Sending shared post...')
    return bot.send_message(
        chat_id=chat_id,
        text=post.permalink
    )


def postLinkToChat(
        bot: telegram.Bot,
        post: Post,
        chat_id: str,
) -> telegram.Message:
    logger.info('Sending shared post...')
    return bot.send_message(
        chat_id=chat_id,
        text=post.message + f'\n[{post.caption}]({post.media_src})'
    )


def postStatusToChat(
        bot: telegram.Bot,
        post: Post,
        chat_id: str,
) -> telegram.Message:
    logger.info('Sending shared post...')
    return bot.send_message(
        chat_id=chat_id,
        text=post.message
    )


@with_caption
def postFileToChat(
        bot: telegram.Bot,
        post: Post,
        chat_id
) -> telegram.Message:
    logger.info('Posting file to chat...')
    return bot.send_message(
        chat_id=chat_id,
        text=post.message + f'\n[descarca fisier]({post.media_src})',
        parse_mode='Markdown'
    )


post_type = {
    "photo": postPhotoToChat,
    "video": postVideoToChat,
    "shared": postSharedToChat,
    "status": postStatusToChat,
    "link": postLinkToChat,
    "file_upload": postFileToChat,
}


def get_facebook_post(graph: facebook.GraphAPI, post_id: str) -> tuple[Optional[dict], str]:
    try:
        # Request to the GraphAPI with the post id and the required fields
        post = graph.get_object(
            id=post_id,
            fields='id,type,attachments{type,url,media,description},message,permalink_url,caption')
        logger.info('The post was successfully retrieved')

    # Error in the Facebook API
    except facebook.GraphAPIError as e:
        logger.error('Error: Could not get Facebook posts.')
        return None, f"get_facebook_post threw an error:\n{e}"

    return post, "Successfully fetched Facebook posts."


def error(bot, update, err):
    bot.send_message(ADMIN, 'Update "{}" caused error "{}"'.format(update, err))
    logger.warning('Update "{}" caused error "{}"'.format(update, err))


def send_post_to_tg(new_post_id: str):
    global ADMIN

    # Loading the settings from the environment
    ADMIN = os.environ['ADMIN']
    channel_id = os.environ['CHANNEL']
    telegram_token = os.environ['TG_TOKEN']
    facebook_token = os.environ['FB_TOKEN']

    graph = facebook.GraphAPI(access_token=facebook_token, version='3.1')
    bot = telegram.Bot(token=telegram_token)

    # Log all errors
    updater = Updater(token=telegram_token)
    dispatcher = updater.dispatcher
    dispatcher.add_error_handler(error)

    new_post, logg_msg = get_facebook_post(graph, new_post_id)

    # If there is an admin chat ID in the settings file
    if ADMIN is not None:
        try:
            # Sends a message to the bot Admin confirming the action
            bot.send_message(
                chat_id=ADMIN,
                text=f'{logg_msg}:{json.dumps(new_post, indent=2)}')
        except TelegramError:
            logger.warning('Admin ID not found.')
            logger.info(logg_msg)
    else:
        logger.info(logg_msg)

    if new_post is not None:
        new_post = Post(new_post)

        post_function = post_type[new_post.type]
        tg_message = post_function(bot, new_post, channel_id)

        # Add a button with the url to the original post
        markup = telegram.InlineKeyboardMarkup(
            [[telegram.InlineKeyboardButton(
                text='Vezi postarea',
                url=new_post.permalink
            )]]
        )
        tg_message.edit_reply_markup(markup)
