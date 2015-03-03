#!/usr/bin/env python
'''Simple "message in a bottle" application
'''
from bottle import debug, post, redirect, request, route, run, template
import sqlite3, subprocess, time

HTML = '''<!DOCTYPE html><html><head><title>{{title}}</title></head>
<body>
%s
</body></html>'''

FORM = '''<form action="/confirmation" method="POST">
Who shall I notify:
<input type="text" name="name"><br />
What is your message:<br />
<textarea name="message" cols="80" rows="25">{{content}}</textarea><br />
<input type="submit" value="Notify">
</form>'''

HTML_FORM = HTML % FORM

CONFIRMATION = '''
<p>{{name}} has been been sent message ID {{id}}:
<blockquote>{{message}}
</blockquote>
<a href="/">Done</a>'''

HTML_CONFIRMATION = HTML % CONFIRMATION

DOCROOT = '''
<p><h3>Current Notices:</h3></p>
<table>
<tr><th>Notice ID</th><th>Recipient</th><th>Date</th><th>Message</th></tr>
%for row in rows:
  %id=row[0]
  <tr>
  %for col in row:
    <td>{{col}}</td>
  %end
    <td>
    <form action="/close" method="POST">
    <input type="submit" value="Close" />
    <input name="entry" type="hidden" value="{{id}}" />
    </form></td>
  </tr>
%end
</table>
<p><h3>{{!prev}}<a href='/notify'>Send new notification</a>{{!next}}</h3></p>
{{!pages}}'''

HTML_ROOT = HTML % DOCROOT

class Model(object):
    '''Maintain the DB for notifications
    '''
    schema_version = 1
    def __init__(self, dbfile='./notifications.db'):
        '''Create table if necessary otherwise use existing data
        '''
        self.filename = dbfile
        self.db = sqlite3.connect(self.filename)
        prep_table = """
          CREATE TABLE IF NOT EXISTS notices
            (id INTEGER PRIMARY KEY ASC AUTOINCREMENT,
             name TEXT NOT NULL,
             message TEXT NOT NULL,
             postdate DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
             closedate DATETIME DEFAULT NULL)"""
        self.db.execute(prep_table)
        self.db.commit()
        self.check_schema()
    def get_open_entry_count(self):
        '''Return count for all open entries'''
        qry = 'SELECT COUNT(id) FROM notices WHERE closedate IS NULL'
        return self.db.execute(qry).fetchone()[0]
    def get_open_entries(self, count=20, offset=0, width=72):
        '''Get some of the open entries and summary of the contents
           Defaults are suitable for the default index/root page
        '''
        offset = offset * count
        get_entries = '''SELECT id, name, postdate, SUBSTR(message, 1, ?)
          FROM notices WHERE closedate IS NULl ORDER BY id DESC
          LIMIT ? OFFSET ?'''
        args = (width, count, offset)
        current = self.db.execute(get_entries, args)
        pagecount = int(self.get_open_entry_count() / count)
        return (current.fetchall(), pagecount)
    def create_entry(self, name, message):
        '''Create a new "open" entry
        '''
        stmt = "INSERT INTO notices (name, message) VALUES (?, ?)"
        newrow = self.db.execute(stmt, (name, message))
        self.db.commit()
        return newrow.lastrowid
    def close_entry(self, entry):
        '''Mark a entry as "closed" (set a closing date on it)
        '''
        chk = "SELECT id, name, postdate, message, closedate FROM notices WHERE id=?"
        row = self.db.execute(chk, (entry,))
        if row:
            row = row.fetchone()
            if row[4] is not None:
                return 'Entry %s was already closed on %s' % (row[0], row[4])
        else:
            return 'Bad entry: Cannot close'
        self.db.execute("UPDATE notices set closedate=DATETIME('NOW') WHERE id=?", (entry,))
        self.db.commit()
        return 'Entry_%s_closed' % row[0]  ## TODO: implement better return value here

    def check_schema(self):
        '''Check schema against self
        '''
        mk_table = '''CREATE TABLE IF NOT EXISTS versions
                      (component TEXT UNIQUE NOT NULL, version INTEGER NOT NULL)'''
        self.db.execute(mk_table) # Fire and forget
        self.db.commit()
        chk_version = "SELECT version FROM versions WHERE component = 'schema'"
        ver = self.db.execute(chk_version).fetchall()
        if not ver or ver[0] < Model.schema_version:
            self.migrate()

    def migrate(self):
        '''Upgrade DB schema
           (Must upgrade this and Model.schema_version for new schema)
        '''
        add_parent_col = 'ALTER TABLE notices ADD COLUMN parent_id INTEGER'
        set_new_version = '''INSERT OR REPLACE INTO versions (component, version)
                             VALUES ('schema', 1)'''
        try:
            self.db.execute(add_parent_col)
            self.db.execute(set_new_version)
            self.db.commit()
        except sqlite3.Error:
            return False  ## TODO: what do we do here?  Log error?
        return True


@route('/')
@route('/<page:int>')
def root(page=0):
    '''App/Doc Root page: show open incidents and link to new entry form'''
    if page is None:
        page = 0
    vals = dict()
    vals['title'] = 'Notification System'
    vals['rows'], pagemax = model.get_open_entries(offset=page)
    if pagemax > 1:
        vals['pages'] = '<p>%s of %s pages</p>' % (page, pagemax)
    else:
        vals['pages'] = ''
    if page < 1:
        vals['prev'] = '&lt;&lt;&nbsp;&nbsp;'
    else:
        prev = max(0, page - 1)
        vals['prev'] = '<a href="/%s">&lt;&lt;</a>&nbsp;&nbsp;' % (prev)
    if page > pagemax - 1:
        vals['next'] = '&nbsp;&nbsp;&gt;&gt;'
    else:
        nxt = min(pagemax, page + 1)
        vals['next'] = '&nbsp;&nbsp;<a href="/%s">&gt;&gt;</a>' % (nxt)
    return template(HTML_ROOT, vals)

@route('/notify')
def notify():
    '''New notification entry form'''
    return template(HTML_FORM, title='Notify', content='')

@post('/close')
def close():
    '''Set closed date on some entry and return to app/doc root page'''
    entry = request.forms.get('entry')
    result = model.close_entry(entry)
    return redirect('/?result=%s' % result)

@route('/confirmation')
def redir():
    '''After confirmation, return to app/doc root page'''
    redirect('/')

@post('/confirmation')
def confirm():
    '''Interstial page to confirm new entry'''
    vals = dict()
    vals['title'] = 'Confirmation'
    vals['name'] = request.forms.get('name')
    vals['message'] = request.forms.get('message')
    vals['id'] = model.create_entry(vals['name'], vals['message'])
    return template(HTML_CONFIRMATION, vals)


class Command(object):
    '''Collection of commands to be invoked from the command line
       These should all be static methods
    '''

    @staticmethod
    def call(cmd, *args, **opts):
        '''If it's a callable then call it'''
        if hasattr(Command, cmd):
            func = getattr(Command, cmd)
            if callable(func):
                return func(*args, **opts)
        return 'Unknown command'

    @staticmethod
    def backup(filename='notifications.db.bak'):
        '''Call sqlite3 .backup command to perform a backup of the DB'''
        filename = '%s.%s' % (filename, int(time.time()))
        cmd = ['sqlite3', '-batch', 'notifications.db', '.backup %s' % filename]
        try:
            retval = subprocess.call(cmd)
        except EnvironmentError, e:
            return (127, 'Unable to execute sqlite3: %s' % e)
        if retval:
            return (retval, 'Some error occurred: %s' % retval)
        else:
            return (retval, 'Success')


if __name__ == '__main__':
    import sys
    arguments = sys.argv[1:]
    if not arguments:  # Start service
        model = Model()
        debug(True)
        run(host='localhost', port=8080)
    else:
        command, line = arguments[0], arguments[1:]
        exitval, msg = Command.call(command, *line)
        print >> sys.stderr, msg
        sys.exit(exitval)

