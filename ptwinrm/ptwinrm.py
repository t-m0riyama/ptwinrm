# -*- coding: utf-8 -*-
#
# This file is part of the ptwinrm project
#
# Copyright (c) 2017 Tiago Coutinho
# Distributed under the MIT license. See LICENSE for more info.

"""WinRM console

Usage:
  winrm [--user=<user>]
        [--encoding=<encoding>]
        [--password=<password>]
        [--transport=<transport>]
        [--server_cert_validation=<validate>]
        [--ssl=<ssl>]
        [--shell=<shell>]
        [--run=<cmd>] <host>

Options:
  -h --help                show this
  --user=<user>            user name
  --encoding=<encoding>    specify console encoding (defaults to stdout encoding)
  --password=<password>    password on the command line
  --transport=<transport>  [default: ntlm]. Valid: 'kerberos', 'ntlm'
  --server_cert_validation=<validate>  [default: validate]. Valid: 'validate', 'ignore'
  --ssl=<use_ssl>          [default: ssl]. Valid: 'ssl', 'plaintext'
  --shell=<shell>          [default: cmd]. Valid: 'cmd', 'powershell'
  --run=<cmd>              command to execute (if not given, a console starts)
"""

from __future__ import unicode_literals
from __future__ import print_function

import sys
from functools import partial

import winrm
import winrm.exceptions
from winrm.protocol import Protocol
import requests.exceptions
from docopt import docopt
from prompt_toolkit import prompt
from prompt_toolkit.keys import Keys
from prompt_toolkit.token import Token
from prompt_toolkit.filters import Always, Never
from prompt_toolkit.styles import style_from_dict
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.key_binding.manager import KeyBindingManager


class WinRMSession(winrm.Session):
    def __init__(self, target, auth, **kwargs):
        username, password = auth
        self.url = self._build_url(target, kwargs.get('ssl', 'ssl'))
        self.protocol = Protocol(
            endpoint=self.url,
            transport=kwargs.get('transport', 'ntlm'),
            username=username,
            password=password,
            server_cert_validation=kwargs.get('server_cert_validation', 'validate'))


class WinRMConsole(object):
    """WinRM Console"""

    def __init__(self, session, encoding, shell):
        self.session = session
        self.encoding = encoding
        self.multiline = False
        self.shell = shell

    @property
    def username(self):
        return self.session.protocol.username

    @property
    def url(self):
        return self.session.url

    def run_cmd_line(self, cmd_line):
        try:
            return self.__run_cmd_line(cmd_line)
        except (winrm.exceptions.InvalidCredentialsError,
                requests.exceptions.ConnectionError) as error:
            print('ERROR:', error)

    def __run_cmd_line(self, cmd_line):
        if not cmd_line.strip():
            return
        if '\n' in cmd_line or self.shell == 'powershell':
            return self.session.run_ps(cmd_line)
        else:
            cmd = cmd_line.split()
            return self.session.run_cmd(cmd[0], cmd[1:])

    def handle_cmd_result(self, result):
        if result is None:
            return
        if result.status_code:
            print(result.std_out.decode(self.encoding))
            if result.std_err:
                print('ERROR ({0}): {1}'.format(result.status_code,
                                            result.std_err.decode(self.encoding)))
            else:
                print('ERROR ({0})'.format(result.status_code))
        else:
            print(result.std_out.decode(self.encoding))
            if result.std_err:
                # ignore CLIXML error
                if not result.std_err.decode(self.encoding).startswith('#< CLIXML'):
                    print('ERROR: {0}'.format(
                        result.std_err.decode(self.encoding)))
        return result

    def toggle_multiline(self):
        self.multiline = not self.multiline
        return self.multiline

    def get_prompt(self):
        if self.shell == 'powershell':
            r = self.run_cmd_line('(pwd).Path')
            return "PS " + r.std_out.strip().decode(self.encoding) + "> "
        else:
            r = self.run_cmd_line('cd')
            return r.std_out.strip().decode(self.encoding) + ">"

    def rep(self, cmd_line):
        result = self.run_cmd_line(cmd_line)
        return self.handle_cmd_result(result)

    def repl(self):
        history = InMemoryHistory()
        auto_suggest = AutoSuggestFromHistory()
        manager = KeyBindingManager.for_prompt()

        @manager.registry.add_binding(Keys.ControlT)
        def _(event):
            def update_multiline():
                multiline = self.toggle_multiline()

                if multiline:
                    event.cli.current_buffer.is_multiline = Always()
                else:
                    event.cli.current_buffer.is_multiline = Never()
                print('Set multiline', multiline and 'ON' or 'off')
            event.cli.run_in_terminal(update_multiline)

        def get_bottom_toolbar_tokens(cli):
            msg = ' Connected as {0} to {1}'.format(self.username, self.url)
            ml = ' Multiline is {0}'.format(self.multiline and 'ON' or 'off')
            return [(Token.Toolbar.Connection, msg),
                    (Token.Toolbar.Multiline, ml)]

        style = style_from_dict({
            Token.Toolbar.Connection: '#ffffff bg:#009900',
            Token.Toolbar.Multiline: '#ffffff bg:#ee0000',
        })

        ppt = partial(prompt, history=history, auto_suggest=auto_suggest,
                      get_bottom_toolbar_tokens=get_bottom_toolbar_tokens,
                      key_bindings_registry=manager.registry,
                      style=style)

        try:
            prompt_msg = self.get_prompt()
        except Exception as e:
            print("ERROR: {}".format(e))
            return
        while True:
            try:
                cmd_line = ppt(prompt_msg, multiline=self.multiline)
                self.rep(cmd_line)
            except (EOFError, KeyboardInterrupt):
                print('\nCtrl-C pressed. Bailing out!')
                break
            except:
                sys.excepthook(*sys.exc_info())


def main():
    opt = docopt(__doc__, help=True)
    user = opt['--user'] or prompt('user: ')
    password = opt['--password'] or prompt('password: ', is_password=True)
    transport = opt['--transport']
    encoding = opt["--encoding"] or sys.stdout.encoding
    server_cert_validation = opt['--server_cert_validation']
    shell = opt['--shell'] or 'cmd'
    ssl = opt['--ssl']
    host = opt['<host>']

    session = WinRMSession(host,
                           (user, password),
                           transport=transport,
                           server_cert_validation=server_cert_validation,
                           ssl=ssl)
    console = WinRMConsole(session, encoding=encoding, shell=shell)

    if opt['--run']:
        cmd_result = console.rep(opt['--run'])
        code = cmd_result.status_code if cmd_result else 1
        sys.exit(code)

    console.repl()


if __name__ == '__main__':
    main()
