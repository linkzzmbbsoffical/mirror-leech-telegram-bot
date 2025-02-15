#!/usr/bin/env python3
from logging import getLogger
from urllib.parse import quote as rquote

from bot import DRIVES_NAMES, DRIVES_IDS, INDEX_URLS
from bot.helper.ext_utils.bot_utils import get_readable_file_size
from bot.helper.mirror_utils.gdrive_utlis.helper import GoogleDriveHelper

LOGGER = getLogger(__name__)


class gdSearch(GoogleDriveHelper):

    def __init__(self, stopDup=False, noMulti=False, isRecursive=True, itemType='', listener=None):
        super().__init__(listener)
        self.__stopDup = stopDup
        self.__noMulti = noMulti
        self.__isRecursive = isRecursive
        self.__itemType = itemType

    def __drive_query(self, dirId, fileName, isRecursive):
        try:
            if isRecursive:
                if self.__stopDup:
                    query = f"name = '{fileName}' and "
                else:
                    fileName = fileName.split()
                    query = "".join(
                        f"name contains '{name}' and "
                        for name in fileName
                        if name != ''
                    )
                    if self.__itemType == "files":
                        query += f"mimeType != '{self.G_DRIVE_DIR_MIME_TYPE}' and "
                    elif self.__itemType == "folders":
                        query += f"mimeType = '{self.G_DRIVE_DIR_MIME_TYPE}' and "
                query += "trashed = false"
                if dirId == "root":
                    return self.service.files().list(q=f"{query} and 'me' in owners",
                                                       pageSize=200, spaces='drive',
                                                       fields='files(id, name, mimeType, size, parents)',
                                                       orderBy='folder, name asc').execute()
                else:
                    return self.service.files().list(supportsAllDrives=True, includeItemsFromAllDrives=True,
                                                     driveId=dirId, q=query, spaces='drive', pageSize=150,
                                                     fields='files(id, name, mimeType, size, teamDriveId, parents)',
                                                     corpora='drive', orderBy='folder, name asc').execute()
            else:
                if self.__stopDup:
                    query = f"'{dirId}' in parents and name = '{fileName}' and "
                else:
                    query = f"'{dirId}' in parents and "
                    fileName = fileName.split()
                    for name in fileName:
                        if name != '':
                            query += f"name contains '{name}' and "
                    if self.__itemType == "files":
                        query += f"mimeType != '{self.G_DRIVE_DIR_MIME_TYPE}' and "
                    elif self.__itemType == "folders":
                        query += f"mimeType = '{self.G_DRIVE_DIR_MIME_TYPE}' and "
                query += "trashed = false"
                return self.service.files().list(supportsAllDrives=True, includeItemsFromAllDrives=True,
                                                 q=query, spaces='drive', pageSize=150,
                                                 fields='files(id, name, mimeType, size)',
                                                 orderBy='folder, name asc').execute()
        except Exception as err:
            err = str(err).replace('>', '').replace('<', '')
            LOGGER.error(err)
            return {'files': []}

    def drive_list(self, fileName):
        if self.listener and self.listener.upDest.startswith('mtp:'):
            drives = self.get_user_drive()
        else:
            drives = zip(DRIVES_NAMES, DRIVES_IDS, INDEX_URLS)
        self.service = self.authorize()
        msg = ""
        fileName = self.escapes(str(fileName))
        contents_no = 0
        telegraph_content = []
        Title = False
        if len(drives) > 1:
            token_service = self.alt_authorize()
            if token_service is not None:
                self.service = token_service
        for drive_name, dir_id, index_url in drives:
            isRecur = False if self.__isRecursive and len(
                dir_id) > 23 else self.__isRecursive
            response = self.__drive_query(dir_id, fileName, isRecur)
            if not response["files"]:
                if self.__noMulti:
                    break
                else:
                    continue
            if not Title:
                msg += f'<h4>Search Result For {fileName}</h4>'
                Title = True
            if drive_name:
                msg += f"╾────────────╼<br><b>{drive_name}</b><br>╾────────────╼<br>"
            for file in response.get('files', []):
                mime_type = file.get('mimeType')
                if mime_type == self.G_DRIVE_DIR_MIME_TYPE:
                    furl = self.G_DRIVE_DIR_BASE_DOWNLOAD_URL.format(
                        file.get('id'))
                    msg += f"📁 <code>{file.get('name')}<br>(folder)</code><br>"
                    msg += f"<b><a href={furl}>Drive Link</a></b>"
                    if index_url:
                        url = f'{index_url}findpath?id={file.get("id")}'
                        msg += f' <b>| <a href="{url}">Index Link</a></b>'
                elif mime_type == 'application/vnd.google-apps.shortcut':
                    furl = self.G_DRIVE_DIR_BASE_DOWNLOAD_URL.format(
                        file.get('id'))
                    msg += f"⁍<a href='{self.G_DRIVE_DIR_BASE_DOWNLOAD_URL.format(file.get('id'))}'>{file.get('name')}" \
                        f"</a> (shortcut)"
                else:
                    furl = self.G_DRIVE_BASE_DOWNLOAD_URL.format(
                        file.get('id'))
                    msg += f"📄 <code>{file.get('name')}<br>({get_readable_file_size(int(file.get('size', 0)))})</code><br>"
                    msg += f"<b><a href={furl}>Drive Link</a></b>"
                    if index_url:
                        url = f'{index_url}findpath?id={file.get("id")}'
                        msg += f' <b>| <a href="{url}">Index Link</a></b>'
                        if mime_type.startswith(('image', 'video', 'audio')):
                            urlv = f'{index_url}findpath?id={file.get("id")}&?a=view'
                            msg += f' <b>| <a href="{urlv}">View Link</a></b>'
                msg += '<br><br>'
                contents_no += 1
                if len(msg.encode('utf-8')) > 39000:
                    telegraph_content.append(msg)
                    msg = ''
            if self.__noMulti:
                break

        if msg != '':
            telegraph_content.append(msg)

        return telegraph_content, contents_no

    def get_user_drive(self):
        dest_id = self.listener.upDest.lstrip('mtp:')
        self.token_path = f'tokens/{self.listener.user_id}.pickle'
        self.use_sa = False
        INDEX = ''
        if self.listener.user_dict.get('index_url'):
            INDEX = self.listener.user_dict['index_url']
        return [('User Choice', dest_id, INDEX)]
