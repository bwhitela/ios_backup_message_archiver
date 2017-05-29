ios_backup_message_archiver.py
==============================

Python tool/script to generate HTML-based archives of messages from iOS backups.

Overview
--------

This Python script is meant to generate HTML archives of chats from an iOS
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

Usage
-----

::

  python ios_backup_message_archiver.py --help
  Usage: ios_backup_message_archiver.py [options] <path to backup directory>

  Options:
    -h, --help            show this help message and exit
    -o OUTPUT_DIR, --outdir=OUTPUT_DIR
                          Directory where the archive will be stored. [default:
                          ~/out]
    -l LOG_FILE, --logfile=LOG_FILE
                          File to write logs. If unspecified, stdout.
    -v, --verbose         Turn on debug logging.
    -q, --quiet           Turn off all logging. This beats all other log
                          options.

Notes About Backups
-------------------

In OS X, iTunes keeps your backups of your iOS device under
``~/Library/Application\ Support/MobileSync/Backup/``.  I do not know where
iTunes keeps them on Windows, but the internet can let you know.  Each backed-up
iOS device will have a separate directory for it.  It gets named with some kind
of hash.  I don't know what that is, but you can easily identify the desired
directory based on last modified time.  That directory is the one you'll need to
supply to this script.  If you have your backups set to be encrypted (something
your employer might enforce), this script will not work.

Notes About Changes
-------------------

As of this commit, this script is functioning with backups from iOS 10.  It
should function with previous versions as it tries to be smart about where to
find necessary files, which have changed locations.  I have not tested this
iteration with any backups before iOS 10.
