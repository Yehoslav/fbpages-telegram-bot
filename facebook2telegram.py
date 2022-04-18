# coding=utf-8
import enum
import json  # Used for tacking last dates
import logging  # Used for logging
import os
import sys  # Used for exiting the program
from datetime import datetime  # Used for date comparison
from enum import Enum
from typing import Optional

import telegram  # telegram-bot-python
from telegram.ext import Updater
from telegram.error import TelegramError, InvalidToken, BadRequest, TimedOut  # Error handling

from flask import Flask, request
import facebook  # facebook-sdk
import youtube_dl  # youtube-dl

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

# youtube-dl
ydl = youtube_dl.YoutubeDL({'outtmpl': '%(id)s%(ext)s'})
ADMIN: int


class PostType(Enum):
    PHOTO = enum.auto()
    VIDEO = enum.auto()
    SHARED = enum.auto()
    STATUS = enum.auto()
    LINK = enum.auto()


class Post:

    def __init__(self, post: dict):
        self.post_id = post['id'] if 'id' in post else None
        self.post_type = PostType[post['type'].upper()] if 'type' in post else None
        self.message = post['message'] if 'message' in post else None
        self.permalink: str = post['permalink_url'] if 'permalink_url' in post else None
        self.post_id = post['id'] if 'id' in post else None
        self.caption = post['caption'] if 'caption' in post else None
        if post['type'] == 'status':
            if 'attachments' in post:
                self.post_type = PostType.SHARED
                self.media_src = post['attachments']['data'][0]['media']['image']['src']
            else:
                self.media_src = None
        if post['type'] == 'link':
            if 'attachments' in post:
                self.post_type = PostType.LINK
                self.atth_url = post['attachments']['data'][0]['url']

        elif post['type'] == 'photo':
            self.media_src = post['attachments']['data'][0]['media']['image']['src']

        elif post['type'] == 'video':
            if self.caption == "youtube.com":
                self.media_src = post['attachments']['data'][0]['media']['source']
            else:
                self.media_src = post['attachments']['data'][0]['url']


def with_caption(func):
    def wrapper(bot: telegram.Bot, direct_link, post_message: str, chat_id,):
        if len(post_message) > 200:
            separate_message = post_message
            post_message = ''
            send_separate = True
        else:
            separate_message = ''
            send_separate = False

        message: Optional[telegram.Message]
        message = func(bot, direct_link, post_message, chat_id)

        if send_separate and message is not None:
            message = message.reply_text(text=separate_message, quote=True)
        elif send_separate and message is None:
            message = bot.send_message(chat_id, text=separate_message + f'\n[link direct]({direct_link})',
                                       parse_mode='Markdown')
        elif message is None:
            message = bot.send_message(chat_id, text=post_message + f'\n[media]({direct_link})', parse_mode='Markdown')

        return message

    return wrapper


@with_caption
def postPhotoToChat(bot: telegram.Bot,
                    direct_link: str,
                    post_message: str,
                    chat_id: str,
                    ) -> Optional[telegram.Message]:
    """
    Posts the post's picture with the appropriate caption.
    """
    try:
        message = bot.send_photo(
            chat_id=chat_id,
            photo=direct_link,
            caption=post_message)
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
def postVideoToChat(bot: telegram.Bot, direct_link: str, post_message: str, chat_id: str)\
        -> Optional:
    """
    This function tries to pass 3 different URLs to the Telegram API
    instead of downloading the video file locally to save bandwidth.

    *First option":  Direct video source
    *Second option": Direct video source from youtube-dl
    *Third option":  Direct video source with smaller resolution
    "Fourth option": Send the video link
    """
    # If youtube link, post the link

    try:
        logger.info('Post video...')
        message = bot.send_video(
            chat_id=chat_id,
            video=direct_link)
        return message

    except TelegramError as e:  # If the API can't send the video
        try:
            if 'youtube.com' in direct_link:
                logger.info('Sending YouTube link...')
                message = bot.send_message(
                    chat_id=chat_id,
                    text=f"{post_message}\n{getDirectURLVideoYDL(direct_link)}")
                return message

            elif 'facebook.com' in direct_link:
                logger.info('Sending Facebook Directlink...')
                message = bot.send_message(
                    chat_id=chat_id,
                    text=f"{post_message}\n{getDirectURLVideoFB(direct_link)}")
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


def postNewPost(bot: telegram.Bot,
                post: Post,
                chat_id: str) -> bool:
    """
    Checks the type of the Facebook post and if it's allowed by the
    settings file, then calls the appropriate function for each type.
    """

    # Telegram doesn't allow media captions with more than 200 characters
    # Send separate message with the post's message
    if post.post_type == PostType.SHARED:
        logger.info('This is a shared post.')
        tg_message = bot.send_message(
            chat_id=chat_id,
            text='Shared post.')
    elif post.post_type == PostType.PHOTO:
        logger.info('Posting photo...')
        tg_message = postPhotoToChat(bot, post.media_src, post.message, chat_id)
        # if send_separate:
        #     tg_message.reply_text(separate_message)
    elif post.post_type == PostType.VIDEO:
        logger.info('Posting video...')
        tg_message = postVideoToChat(bot, post.media_src, post.message, chat_id)
        # if send_separate and status == Status.SUCCESS:
        #     tg_message.reply_text(separate_message)
    elif post.post_type == PostType.STATUS:
        logger.info('Posting status...')
        tg_message = bot.send_message(
            chat_id=chat_id,
            text=post.message)
    elif post.post_type == PostType.LINK:
        logger.info('Posting link...')
        tg_message = bot.send_message(
            chat_id=chat_id,
            text=post.message + f'\n[{post.caption}]({post.atth_url})',
            parse_mode='Markdown'
        )
    else:
        logger.warning('This post is a {}, skipping...'.format(post.post_type))
        return False

    markup = telegram.InlineKeyboardMarkup(
        [[telegram.InlineKeyboardButton(
            text='Vezi postarea',
            url=post.permalink
        )]]
    )
    tg_message.edit_reply_markup(markup)
    return True


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
    server = False
    ADMIN = os.environ['ADMIN'] if server else 407628660
    # channel_id = os.environ['CHANNEL'] if server else '-1001649433472'
    channel_id = ADMIN
    telegram_token = os.environ['TG_TOKEN'] if server else \
            '2063032857:AAHMVw8Glz0IU2Z1zaug-iYjpn9CKr-X8_M'
    facebook_token = os.environ['FB_TOKEN'] if server else  \
            'EAAEncCS8JxIBAIinLGoyM2qO7h4TCxQsYRmghMZCWRP4CDwcsk80M4T5B9xfv11jhTqY7mwBGLGJZAFhH6JAZAhICpt074LXBO6cwVZBVZB61p0dNcFVbmmUHfkNFZBjhmTZA9wFAZB8gfuqWUF0rU9MwgVbfTvNkf2LbjTbgAjukViZCWnF5zPdl'

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
                text=f'{logg_msg}:{new_post}')
        except TelegramError:
            logger.warning('Admin ID not found.')
            logger.info(logg_msg)
    else:
        logger.info(logg_msg)

    if new_post is not None:
        new_post = Post(new_post)
        if postNewPost(bot, new_post, channel_id):
            logger.info('Posted the post')
        else:
            logger.critical('Some error occurred while posting the posts.')
