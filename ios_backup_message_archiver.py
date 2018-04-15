# Copyright (c) 2015-2017 Brett Whitelaw
# All rights reserved.
# Unauthorized redistribution prohibited.

"""This Python script is meant to generate HTML archives of chats from an iOS
backup.  Each chat (which can be with a single person or multiple) is created
as a single HTML file with a similarly named directory for attachments.  The
filenames, in this version, are named with the chat ID (used in the SQLite DB)
and all the contacts that are in the chat.  Image attachments are inserted
into the HTML file and all attachments have a link inserted into the HTML for
ease of access.  As much information as possible is inserted into the HTML,
like timestamps (including read time, when known) and messaging service (SMS
or iMessage).  This script now, also, reads the address book database from the
backup and uses that information to map the phone number or email address in the
message to a first and last name or the company name.  These are used in the
HTML and file names.

:Author: Brett Whitelaw (GitHub: bwhitela)
:Date: 2015/12/31
:Last Update: 2018/04/14
"""

import hashlib
import logging
import optparse
import os
import shutil
import sqlite3
import sys
import time


MAGIC_DATE_NUMBER = 978307200
NANOSECONDS = 1000000000
SMS_DB_FILE_NAME = '3d0d7e5fb2ce288813306e4d4636395e047a3d28'
CONTACTS_DB_FILE_NAME = '31bb7ba8914766d4ba40d6dfb6113c8b614be442'


# A chat could have 1 or more people (group messaging) and a single person could be in more than 1 chat.
CHAT_HANDLE_JOIN_FIELDS = ['chat_id',   # An integer used to identify the chat.
                           'handle_id'] # An integer used to identify a contact / phone number.

CHAT_MESSAGE_JOIN_FIELDS = ['chat_id',    # An integer used to identify the chat.
                            'message_id'] # Integer identifier for a single message sent/received.

CHAT_FIELDS = ['chat_identifier'] # A string used to identify the chat, SMS and iMessages together.
               # 'ROWID'          # Used elsewhere as chat_id (integer).

MESSAGE_FIELDS = ['text',       # Text from the message.
                  'handle_id',  # An integer identifier that maps to a contact / phone number.
                  'service',    # SMS or iMessage.
                  'date',       # Date sent. Epoch minus magic date number.
                  'date_read',  # Date read (probably 0 if unknown). Epoch minus magic date number.
                  'is_from_me', # 1 = I sent it, 0 = I received it.
                  'is_read']    # 1 = the message was read, 0 = the message was not read (or we don't know).
                  # 'ROWID'     # Used elsewhere as message_id (integer).

HANDLE_FIELDS = ['ROWID', # Used elsewhere as handle_id (integer).
                 'id']    # Phone number or email.

MESSAGE_ATTACHMENT_JOIN_FIELDS = ['message_id',    # Integer identifier for a single message sent/received.
                                  'attachment_id'] # Integer identifier for a single attachment file.
ATTACHMENT_FIELDS = ['ROWID',    # Used elsewhere as attachment_id (integer).
                     'filename'] # Path on iOS.


def get_handle_to_contact(filename, log):
    """Get information from the SQLite DB about contacts.

    :Parameters:
        - `filename`: Path to the SQLite DB file (as a string).
        - `log`: Log object.

    :Returns:
        A dictionary mapping contact handle ID (integer) to contact information
        (phone number ('12223334444') or email as a string).

    :Exceptions:
        Standard exceptions from sqlite3 library.
    """
    conn = sqlite3.connect(filename)
    c = conn.cursor()
    c.execute("SELECT %s FROM `handle`;" % (', '.join(HANDLE_FIELDS),))
    result = c.fetchall()
    conn.close()

    # Create a mapping from handle to contact information.
    handle_contact_map = {}
    for handle_id, contact in result:
        if contact.startswith('+'):
            contact = contact.lstrip('+')
        handle_contact_map[handle_id] = contact
    # Handle a new oddity seen in iOS 10 where a handle ID is 0 in a message
    # but is not in handle table.
    if not handle_contact_map.get(0):
        handle_contact_map[0] = 'me-or-null'
    return handle_contact_map

def get_contacts_in_chat(filename, log):
    """Get information from the SQLite DB about contacts in chats.

    :Parameters:
        - `filename`: Path to the SQLite DB file (as a string).
        - `log`: Log object.

    :Returns:
        A dictionary mapping a chat identifier (string) to a list of contacts
        (handle ID (integer)).

    :Exceptions:
        Standard exceptions from sqlite3 library.
    """
    # Users in a chat.
    chat_and_chat_handle_join = CHAT_HANDLE_JOIN_FIELDS + CHAT_FIELDS
    sql = """SELECT %s
    FROM `chat_handle_join`
    INNER JOIN `chat`
    ON chat_handle_join.chat_id=chat.ROWID
    ORDER BY chat_identifier ASC;"""
    conn = sqlite3.connect(filename)
    c = conn.cursor()
    c.execute(sql % (', '.join(chat_and_chat_handle_join),))
    result = c.fetchall()
    conn.close()

    contacts_in_chat = {}
    for chat_id, handle_id, chat_identifier in result:
        if chat_identifier not in contacts_in_chat:
            contacts_in_chat[chat_identifier] = []
        contacts_in_chat[chat_identifier].append(handle_id)
    return contacts_in_chat

def get_chat_coversations(filename, log):
    """Get information from the SQLite DB about messages in chats.

    :Parameters:
        - `filename`: Path to the SQLite DB file (as a string).
        - `log`: Log object.

    :Returns:
        A dictionary mapping a chat identifier (string) to a list of
        dictionaries that represent messages.  These contain a mapping of column
        name to column data from 'message' and 'chat_message_join' tables.  It
        looks something like:
        {<chat_identifier>: [{'ROWID': <ROWID>, 'text': <text>, ...}, {...}, ...], ...}

    :Exceptions:
        Standard exceptions from sqlite3 library.
    """
    # [ROWID, text, handle_id, service, date, date_read, is_from_me, is_read,
    #  chat_id, message_id]
    message_and_chat_message_join = MESSAGE_FIELDS + CHAT_MESSAGE_JOIN_FIELDS + CHAT_FIELDS
    sql = """SELECT %s
    FROM `message`
    INNER JOIN `chat_message_join`
    ON message.ROWID=chat_message_join.message_id
    INNER JOIN `chat`
    ON chat_message_join.chat_id=chat.ROWID
    ORDER BY message_id ASC;"""
    conn = sqlite3.connect(filename)
    c = conn.cursor()
    c.execute(sql % (', '.join(message_and_chat_message_join),))
    result = c.fetchall()
    conn.close()

    conversations = {}
    for message_row in result:
        message_info = dict(zip(message_and_chat_message_join, message_row))
        # Dates appear to be in nanoseconds, now. Probably changed around iOS
        # 11. This code wants seconds, as does Python.
        if message_info['date'] > NANOSECONDS:
            message_info['date'] = int(message_info['date'] / NANOSECONDS)
        if message_info['date_read'] > NANOSECONDS:
            message_info['date_read'] = int(message_info['date_read'] / NANOSECONDS)
        if not message_info['chat_identifier'] in conversations:
            conversations[message_info['chat_identifier']] = []
        conversations[message_info['chat_identifier']].append(message_info)
    return conversations

def convert_attachment_name(name, log):
    """Generate the hashed filename of the attachment in the iOS backup.

    In the backup directory, the attachments are named based on tweaking the
    iOS file path and taking a hash of it.  Simply, a leading chunk is
    replaced and the SHA1 hash is taken of the string.

    :Parameters:
        - `name`: Full path to the attachment on the iOS filesystem (string).
        - `log`: Log object.

    :Returns:
        A string of the hashed filename that can be found in the iOS backup
        directory.
    """
    # Replace the '/var/mobile/' or '~/' with 'MediaDomain-'.
    # http://apple.stackexchange.com/questions/77432/location-of-message-attachments-in-ios-6-backup
    if name.startswith('/var/mobile/'):
        new_name = 'MediaDomain-' + name.lstrip('/var/mobile/')
    elif name.startswith('~/'):
        new_name = 'MediaDomain-' + name.lstrip('~/')
    else:
        log.warn('Bad data in the attachments table. Bad filename: %s', name)
        new_name = ''
    # Take the SHA1 hash of the above filename.
    hashed_name = hashlib.sha1(new_name).hexdigest()
    return hashed_name

def get_message_attachments(filename, log):
    """Get information from the SQLite DB about message attachments.

    :Parameters:
        - `filename`: Path to the SQLite DB file (as a string).
        - `log`: Log object.

    :Returns:
        A dictionary mapping a message ID (integer) to a list of tuples that
        represent all the attachments to that message.  The tuples contain the
        filename of the attachment in the iOS backup directory (string) and
        the original filename on the iOS filesystem (string).

    :Exceptions:
        Standard exceptions from sqlite3 library.
    """
    # [message_id, attachment_id, ROWID, filename]
    message_attachment_fields = MESSAGE_ATTACHMENT_JOIN_FIELDS + ATTACHMENT_FIELDS
    sql = """SELECT %s
    FROM `message_attachment_join`
    INNER JOIN `attachment`
    ON message_attachment_join.attachment_id=attachment.ROWID;"""
    conn = sqlite3.connect(filename)
    c = conn.cursor()
    c.execute(sql % (', '.join(message_attachment_fields),))
    result = c.fetchall()
    conn.close()

    attachments = {}
    for attachment_row in result:
        attachment_info = dict(zip(message_attachment_fields, attachment_row))
        if not attachment_info['message_id'] in attachments:
            attachments[attachment_info['message_id']] = []
        attachment_filename = convert_attachment_name(attachment_info['filename'], log)
        orig_filename = os.path.basename(attachment_info['filename'])
        attachments[attachment_info['message_id']].append((attachment_filename,
                                                           orig_filename))
    return attachments


def normalize_phone_number(phone_number):
    """Attempts to normalize the phone number provided.

    This will remove all typical separator charactors and then attach the
    country code of '1' in the event a country code doesn't appear to be
    present.

    :Parameters:
        - `phone_number`: The phone number to be normalized (as a string).

    :Returns:
        A string that represents the normalized version of the phone number
        provided.

    :Exceptions:
        None.
    """
    if phone_number.startswith('+'):
        phone_number = phone_number.lstrip('+')
    phone_number = phone_number.replace('(', '').replace(')', '')
    phone_number = phone_number.replace('-', '').replace('.', '')
    phone_number = phone_number.replace(' ', '').replace(u'\xa0', '')
    if len(phone_number) == 10:
        phone_number = '1' + phone_number
    return phone_number

def get_contacts_map(filename, log):
    """Get information from the SQLite DB about contacts.

    :Parameters:
        - `filename`: Path to the SQLite DB file (as a string).
        - `log`: Log object.

    :Returns:
        A dictionary mapping a contact identifier (string), that being a
        normalized phone number or an email address, to a name, that being a
        first and last name, if available, or a company name (string).

    :Exceptions:
        Standard exceptions from sqlite3 library.
    """
    contacts_map = {}

    sql = """SELECT ABMultiValue.value AS Email, ABPerson.first AS FirstName,
    ABPerson.last AS LastName, ABPerson.organization as Organization
    FROM ABMultiValue
    LEFT JOIN ABPerson ON ABMultiValue.record_id = ABPerson.ROWID
    WHERE ABMultiValue.property = 4;"""
    conn = sqlite3.connect(filename)
    c = conn.cursor()
    c.execute(sql)
    result = c.fetchall()
    conn.close()
    for email, first, last, org in result:
        names = [name for name in [first, last] if name is not None]
        if not names:
            contact = org
        else:
            contact = ' '.join(names)
        contacts_map[email] = contact

    sql = """SELECT ABMultiValue.value AS Number, ABPerson.first AS FirstName,
    ABPerson.last AS LastName, ABPerson.organization as Organization
    FROM ABMultiValue
    LEFT JOIN ABPerson ON ABMultiValue.record_id = ABPerson.ROWID
    WHERE ABMultiValue.property = 3;"""
    conn = sqlite3.connect(filename)
    c = conn.cursor()
    c.execute(sql)
    result = c.fetchall()
    conn.close()
    for number, first, last, org in result:
        names = [name for name in [first, last] if name is not None]
        if not names:
            contact = org
        else:
            contact = ' '.join(names)
        contacts_map[normalize_phone_number(number)] = contact

    return contacts_map


def parse_cmd_line():
    """Parse the options and arguments from the command line.

    :Returns:
        opts, args
    """
    usage = "usage: %prog [options] <path to backup directory>"
    # Standard location is ~/Library/Application\ Support/MobileSync/Backup
    parser = optparse.OptionParser(usage=usage)
    parser.add_option('-o', '--outdir', dest='output_dir',
                      help='Directory where the archive will be stored. [default: %default]',
                      default='~/out')
    parser.add_option('-l', '--logfile', dest='log_file',
                      help='File to write logs. If unspecified, stdout.')
    parser.add_option('-v', '--verbose', dest='verbose',
                      help='Turn on debug logging.',
                      action="store_true", default=False)
    parser.add_option('-q', '--quiet', dest='quiet',
                      help='Turn off all logging. This beats all other log options.',
                      action="store_true", default=False)
    opts, args = parser.parse_args()
    return opts, args


HTML_START = """
<html>
    <head>
    <title>Conversation with %s</title>
    <style>
        .message {margin: 10 0 10 0;}
        dt.sender_me {font-weight: bold;
                      color: blue;
                      text-decoration: underline;}
        dt.sender_them {font-weight: bold;
                        color: red;
                        text-decoration: underline;}
        dd.text {margin: 0;}
        dd.attachment {margin: 0;}
        dd.readtime {margin: 0;
                     font-size: 80%%;
                     font-style: italic;
                     color: grey;}
    </style>
    </head>
    <body>
    <dl>
"""
HTML_END = """
    </dl>
    </body>
</html>
"""


def main():
    opts, args = parse_cmd_line()

    # Logging setup.
    log = logging.getLogger('iOS_messages_exporter')
    if opts.log_file:
        log.addHandler(logging.FileHandler(opts.log_file))
    elif opts.quiet:
        log.addHandler(logging.NullHandler())
    else:
        log.addHandler(logging.StreamHandler(sys.stdout))
    if opts.verbose:
        log.setLevel(logging.DEBUG)

    # Paths from command line.
    backup_dir = args[0]
    sms_db_file = os.path.join(backup_dir, SMS_DB_FILE_NAME)
    if not os.access(sms_db_file, os.F_OK):
        sms_db_file = os.path.join(backup_dir, SMS_DB_FILE_NAME[0:2], SMS_DB_FILE_NAME)
    contacts_db_file = os.path.join(backup_dir, CONTACTS_DB_FILE_NAME)
    if not os.access(contacts_db_file, os.F_OK):
        contacts_db_file = os.path.join(backup_dir, CONTACTS_DB_FILE_NAME[0:2], CONTACTS_DB_FILE_NAME)
    destination_dir = opts.output_dir

    # Someone didn't make the destination directory yet.
    if not os.access(destination_dir, os.F_OK):
        os.mkdir(destination_dir)

    # SQLite data.
    contacts_in_chat = get_contacts_in_chat(sms_db_file, log)
    handle_contact_map = get_handle_to_contact(sms_db_file, log)
    conversations = get_chat_coversations(sms_db_file, log)
    attachments = get_message_attachments(sms_db_file, log)
    contacts_map = get_contacts_map(contacts_db_file, log)

    for id, conversation in conversations.iteritems():
        chat_contacts = [handle_contact_map[h] for h in contacts_in_chat[id]]
        chat_contacts = [contacts_map.get(contact, contact)
                         for contact in chat_contacts]
        # Because unique contact IDs are created for both SMS and iMessage on
        # the same phone number, these need to be de-duped.
        chat_contacts = list(set(chat_contacts))
        filebase = '%s_%s' % (id, '_'.join(['-'.join(contact.split(' '))
                                            for contact in chat_contacts]))
        filename = filebase + '.html'
        filepath = os.path.join(destination_dir, filename)
        attachment_dir = os.path.join(destination_dir, filebase)
        os.mkdir(attachment_dir)
        with open(filepath, mode='w') as fh:
            fh.write(HTML_START % ', '.join(chat_contacts))

            for message in conversation:
                try:
                    message_parts = []

                    # Name and service:
                    if message['is_from_me']:
                        my_string = '<dt class="sender_me">Me [%s]</dt>' % (message['service'],)
                    else:
                        contact = handle_contact_map[message['handle_id']]
                        contact_name = contacts_map.get(contact, contact)
                        my_string = '<dt class="sender_them">%s (%s) [%s]</dt>' % (contact_name, contact, message['service'])
                    message_parts.append(my_string)

                    # Sent time and message text:
                    message_time = time.localtime(MAGIC_DATE_NUMBER + message['date'])
                    message_time_str = time.strftime('%Y-%m-%d %H:%M:%S %Z', message_time)
                    if message['text'] is None:
                        my_string = '<dd class="text">[%s] [no text]</dd>' % (message_time_str,)
                    else:
                        message_text = '<br>'.join(message['text'].split('\n'))
                        my_string = '<dd class="text">[%s] %s</dd>' % (message_time_str, message_text)
                    message_parts.append(my_string)

                    # Attachments:
                    if message['message_id'] in attachments:
                        for attachment_filename, true_filename in attachments[message['message_id']]:
                            unique_filename = '%s-%s' % (attachment_filename, true_filename)
                            file_from = os.path.join(backup_dir, attachment_filename)
                            if not os.access(file_from, os.F_OK):
                                file_from = os.path.join(backup_dir, attachment_filename[0:2], attachment_filename)
                                if not os.access(file_from, os.F_OK):
                                    my_string = '<dd class="attachment">Missing attachment (%s).</dd>' % (unique_filename,)
                                    message_parts.append(my_string)
                                    continue
                            file_to = os.path.join(attachment_dir, unique_filename)
                            shutil.copyfile(file_from, file_to)
                            file_link = os.path.join(filebase, unique_filename)
                            if unique_filename.split('.')[-1].lower() in ['jpeg', 'jpg', 'png', 'gif', 'svg']:
                                my_string = '<dd class="attachment"><img src="%s" width=50%% /></dd>' % (file_link,)
                                message_parts.append(my_string)
                            my_string = '<dd class="attachment"><a href="%s">(%s)</a></dd>' % (file_link, unique_filename)
                            message_parts.append(my_string)

                    # Read time if applicable:
                    if message['service'] == 'iMessage' and message['is_read'] == 1 and message['date_read'] != 0:
                        read_time = time.localtime(MAGIC_DATE_NUMBER + message['date_read'])
                        read_time_str = time.strftime('%Y-%m-%d %H:%M:%S %Z', read_time)
                        my_string = '<dd class="readtime">Read at: %s</dd>' % (read_time_str,)
                        message_parts.append(my_string)

                    message_template = '<div class="message">\n%s\n</div>\n'
                    all_message_parts = message_template % ('\n'.join(message_parts),)
                    fh.write(all_message_parts.encode('utf8'))

                except Exception as e:
                    log.debug('An error occurred on message: %s', message)
                    log.exception('Unexpected error: %s', e)

            fh.write(HTML_END)


if __name__ == "__main__":
    main()
