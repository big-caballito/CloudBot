from fnmatch import fnmatch

from sqlalchemy import Table, Column, UniqueConstraint, PrimaryKeyConstraint, String, Boolean

from cloudbot import hook
from cloudbot.util import database

table = Table(
    "ignored",
    database.metadata,
    Column("connection", String(25)),
    Column("channel", String(25)),
    Column("mask", String(250)),
    Column("status", Boolean, default=True),
    UniqueConstraint("connection", "channel", "mask", "status"),
    PrimaryKeyConstraint("connection", "channel", "mask")
)


@hook.on_start
def load_cache(event):
    global ignore_cache
    ignore_cache = []

    with event.db_session() as db:
        rows = db.execute(table.select()).fetchall()

    for row in rows:
        conn = row["connection"]
        chan = row["channel"]
        mask = row["mask"]
        ignore_cache.append((conn, chan, mask))


def add_ignore(event, conn, chan, mask):
    if (conn, chan) in ignore_cache:
        return

    with event.db_session() as db:
        db.execute(table.insert().values(connection=conn, channel=chan, mask=mask))
        db.commit()

    load_cache(event)


def remove_ignore(event, conn, chan, mask):
    with event.db_session() as db:
        db.execute(table.delete().where(table.c.connection == conn).where(table.c.channel == chan)
                   .where(table.c.mask == mask))
        db.commit()

    load_cache(event)


def is_ignored(conn, chan, mask):
    mask_cf = mask.casefold()
    for _conn, _chan, _mask in ignore_cache:
        _mask_cf = _mask.casefold()
        if _chan == "*":
            # this is a global ignore
            if fnmatch(mask_cf, _mask_cf):
                return True
        else:
            # this is a channel-specific ignore
            if not (conn, chan) == (_conn, _chan):
                continue
            if fnmatch(mask_cf, _mask_cf):
                return True


@hook.sieve(priority=50)
def ignore_sieve(event):
    """
    :type event: cloudbot.event.Event
    """
    _hook = event.hook

    # don't block event hooks
    if _hook.type in ("irc_raw", "event"):
        return event

    # don't block an event that could be unignoring
    if _hook.type == "command" and event.triggered_command in ("unignore", "global_unignore"):
        return event

    if event.mask is None:
        # this is a server message, we don't need to check it
        return event

    if is_ignored(event.conn.name, event.chan, event.mask):
        return None

    return event


def get_user(conn, text):
    users = conn.memory.get("users", {})
    user = users.get(text)

    if user is None:
        mask = text
    else:
        mask = "*!*@{host}".format_map(user)

    if '@' not in mask:
        mask += "!*@*"

    return mask


@hook.command(permissions=["ignore", "chanop"])
def ignore(text, chan, conn, notice, admin_log, nick, event):
    """<nick|mask> -- ignores all input from <nick|mask> in this channel."""
    target = get_user(conn, text)

    if is_ignored(conn.name, chan, target):
        notice("{} is already ignored in {}.".format(target, chan))
    else:
        admin_log("{} used IGNORE to make me ignore {} in {}".format(nick, target, chan))
        notice("{} has been ignored in {}.".format(target, chan))
        add_ignore(event, conn.name, chan, target)


@hook.command(permissions=["ignore", "chanop"])
def unignore(text, chan, conn, notice, nick, admin_log, event):
    """<nick|mask> -- un-ignores all input from <nick|mask> in this channel."""
    target = get_user(conn, text)

    if not is_ignored(conn.name, chan, target):
        notice("{} is not ignored in {}.".format(target, chan))
    else:
        admin_log("{} used UNIGNORE to make me stop ignoring {} in {}".format(nick, target, chan))
        notice("{} has been un-ignored in {}.".format(target, chan))
        remove_ignore(event, conn.name, chan, target)


@hook.command(permissions=["botcontrol"])
def global_ignore(text, conn, notice, nick, admin_log, event):
    """<nick|mask> -- ignores all input from <nick|mask> in ALL channels."""
    target = get_user(conn, text)

    if is_ignored(conn.name, "*", target):
        notice("{} is already globally ignored.".format(target))
    else:
        notice("{} has been globally ignored.".format(target))
        admin_log("{} used GLOBAL_IGNORE to make me ignore {} everywhere".format(nick, target))
        add_ignore(event, conn.name, "*", target)


@hook.command(permissions=["botcontrol"])
def global_unignore(text, conn, notice, nick, admin_log, event):
    """<nick|mask> -- un-ignores all input from <nick|mask> in ALL channels."""
    target = get_user(conn, text)

    if not is_ignored(conn.name, "*", target):
        notice("{} is not globally ignored.".format(target))
    else:
        notice("{} has been globally un-ignored.".format(target))
        admin_log("{} used GLOBAL_UNIGNORE to make me stop ignoring {} everywhere".format(nick, target))
        remove_ignore(event, conn.name, "*", target)
