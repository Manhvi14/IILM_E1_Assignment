
import logging
import os
import sys
import webbrowser
import numpy as np
import pandas as pd
try:
    # See: spyder-ide/spyder#10221
    if os.environ.get('SSH_CONNECTION') is None:
        import keyring
except Exception:
    pass

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QMessageBox


from spyder.config.manager import CONF
from spyder.config.base import _, running_under_pytest
from spyder.py3compat import PY2
from spyder.utils.external import github
from spyder.widgets.github.gh_login import DlgGitHubLogin


def _logger():
    return logging.getLogger(__name__)


class BaseBackend(object):

    def __init__(self, formatter, button_text, button_tooltip,
                 button_icon=None, need_review=True, parent_widget=None):
        """
        :param formatter: the associated formatter (see :meth:`set_formatter`)
        :param button_text: Text of the associated button in the report dialog
        :param button_icon: Icon of the associated button in the report dialog
        :param button_tooltip: Tooltip of the associated button in the report
            dialog
        :param need_review: True to show the review dialog before submitting.
            Some backends (such as the email backend) do not need a review
            dialog as the user can already review it before sending the final
            report
        """
        self.formatter = formatter
        self.button_text = button_text
        self.button_tooltip = button_tooltip
        self.button_icon = button_icon
        self.need_review = need_review
        self.parent_widget = parent_widget

    def set_formatter(self, formatter):

        self.formatter = formatter

    def send_report(self, title, body, application_log=None):

        raise NotImplementedError


class GithubBackend(BaseBackend):
   
    def __init__(self, gh_owner, gh_repo, formatter=None, parent_widget=None):
       
        super(GithubBackend, self).__init__(
            formatter, "Submit on github",
            "Submit the issue on our issue tracker on github", None,
            parent_widget=parent_widget)
        self.gh_owner = gh_owner
        self.gh_repo = gh_repo
        self._show_msgbox = True  # False when running the test suite

    def send_report(self, title, body, application_log=None):
        _logger().debug('sending bug report on github\ntitle=%s\nbody=%s',
                        title, body)

        # Credentials
        credentials = self.get_user_credentials()
        token = credentials['token']
        remember_token = credentials['remember_token']

        if token is None:
            return False
        _logger().debug('got user credentials')

        # upload log file as a gist
        if application_log:
            url = self.upload_log_file(application_log)
            body += '\nApplication log: %s' % url
        try:
            gh = github.GitHub(access_token=token)
            repo = gh.repos(self.gh_owner)(self.gh_repo)
            ret = repo.issues.post(title=title, body=body)
        except github.ApiError as e:
            _logger().warning('Failed to send bug report on Github. '
                              'response=%r', e.response)
            # invalid credentials
            if e.response.code == 401:
                if self._show_msgbox:
                    QMessageBox.warning(
                        self.parent_widget, _('Invalid credentials'),
                        _('Failed to create Github issue, '
                          'invalid credentials...'))
            else:
                # other issue
                if self._show_msgbox:
                    QMessageBox.warning(
                        self.parent_widget,
                        _('Failed to create issue'),
                        _('Failed to create Github issue. Error %d') %
                        e.response.code)
            return False
        else:
            issue_nbr = ret['number']
            if self._show_msgbox:
                ret = QMessageBox.question(
                    self.parent_widget, _('Issue created on Github'),
                    _('Issue successfully created. Would you like to open the '
                      'issue in your web browser?'))
            if ret in [QMessageBox.Yes, QMessageBox.Ok]:
                webbrowser.open(
                    'https://github.com/%s/%s/issues/%d' % (
                        self.gh_owner, self.gh_repo, issue_nbr))
            return True

    def _get_credentials_from_settings(self):
        """Get the stored credentials if any."""
        remember_token = CONF.get('main', 'report_error/remember_token')
        return remember_token

    def _store_token(self, token, remember=False):
        """Store token for future use."""
        if token and remember:
            try:
                keyring.set_password('github', 'token', token)
            except Exception:
                if self._show_msgbox:
                    QMessageBox.warning(self.parent_widget,
                                        _('Failed to store token'),
                                        _('It was not possible to securely '
                                          'save your token. You will be '
                                          'prompted for your Github token '
                                          'next time you want to report '
                                          'an issue.'))
                remember = False
        CONF.set('main', 'report_error/remember_token', remember)


    def get_user_credentials(self):
        """Get user credentials with the login dialog."""
        token = None
        remember_token = self._get_credentials_from_settings()
        valid_py_os = not (PY2 and sys.platform.startswith('linux'))
        if remember_token and valid_py_os:
            # Get token from keyring
            try:
                token = keyring.get_password('github', 'token')
            except Exception:
                # No safe keyring backend
                if self._show_msgbox:
                    QMessageBox.warning(self.parent_widget,
                                        _('Failed to retrieve token'),
                                        _('It was not possible to retrieve '
                                          'your token. Please introduce it '
                                          'again.'))

        if not running_under_pytest():
            credentials = DlgGitHubLogin.login(
                self.parent_widget,
                token,
                remember_token)

            if credentials['token'] and valid_py_os:
                self._store_token(credentials['token'],
                                  credentials['remember_token'])
                CONF.set('main', 'report_error/remember_token',
                         credentials['remember_token'])
        else:
            return dict(token=token,
                        remember_token=remember_token)

        return credentials

    def upload_log_file(self, log_content):
        gh = github.GitHub()
        try:
            qApp = QApplication.instance()
            qApp.setOverrideCursor(Qt.WaitCursor)
            ret = gh.gists.post(
                description="SpyderIDE log", public=True,
                files={'SpyderIDE.log': {"content": log_content}})
            qApp.restoreOverrideCursor()
        except github.ApiError:
            _logger().warning('Failed to upload log report as a gist')
            return '"Failed to upload log file as a gist"'
        else:
            return ret['html_url']
