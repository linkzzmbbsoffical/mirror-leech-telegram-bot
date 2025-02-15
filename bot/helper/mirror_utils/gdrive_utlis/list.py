#!/usr/bin/env python3
from logging import getLogger
from asyncio import wait_for, Event, wrap_future
from aiofiles.os import path as aiopath
from pyrogram.handlers import CallbackQueryHandler
from pyrogram.filters import regex, user
from functools import partial
from time import time
from tenacity import RetryError
from natsort import natsorted

from bot import config_dict, user_data
from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import sendMessage, editMessage
from bot.helper.ext_utils.bot_utils import new_thread, get_readable_file_size, new_task, get_readable_time, update_user_ldata
from bot.helper.mirror_utils.gdrive_utlis.helper import GoogleDriveHelper

LOGGER = getLogger(__name__)


LIST_LIMIT = 6


@new_task
async def id_updates(_, query, obj):  # sourcery skip: avoid-builtin-shadow
    await query.answer()
    message = query.message
    data = query.data.split()
    if data[1] == 'cancel':
        obj.id = 'Task has been cancelled!'
        obj.is_cancelled = True
        obj.event.set()
        await message.delete()
        return
    if obj.query_proc:
        return
    obj.query_proc = True
    if data[1] == 'pre':
        obj.iter_start -= LIST_LIMIT * obj.page_step
        await obj.get_path_buttons()
    elif data[1] == 'nex':
        obj.iter_start += LIST_LIMIT * obj.page_step
        await obj.get_path_buttons()
    elif data[1] == 'back':
        if data[2] == 'dr':
            await obj.choose_token()
        else:
            await obj.get_pevious_id()
    elif data[1] == 'dr':
        index = int(data[2])
        i = obj.drives[index]
        obj.id = i['id']
        obj.parents = [{'id': i['id'], 'name': i['name']}]
        await obj.get_items()
    elif data[1] == 'pa':
        index = int(data[3])
        i = obj.items_list[index]
        obj.id = i['id']
        if data[2] == 'fo':
            obj.parents.append({'id': i['id'], 'name': i['name']})
            await obj.get_items()
        else:
            await message.delete()
            obj.event.set()
    elif data[1] == 'ps':
        if obj.page_step == int(data[2]):
            return
        obj.page_step = int(data[2])
        await obj.get_path_buttons()
    elif data[1] == 'root':
        obj.id = obj.parents[0]['id']
        obj.parents = obj.parents[0]
        await obj.get_items()
    elif data[1] == 'itype':
        obj.item_type = data[2]
        await obj.get_items()
    elif data[1] == 'cur':
        await message.delete()
        obj.event.set()
    elif data[1] == 'def':
        id = obj.id if obj.token_path == 'token.pickle' else f'mtp:{obj.id}'
        if id != obj.user_dict.get('gdrive_id'):
            update_user_ldata(obj.user_id, 'gdrive_id', id)
            await obj.get_items_buttons()
            if config_dict['DATABASE_URL']:
                await DbManger().update_user_data(obj.user_id)
    elif data[1] == 'owner':
        obj.token_path = 'token.pickle'
        obj.id = ''
        obj.parents = []
        await obj.list_drives()
    elif data[1] == 'user':
        obj.token_path = obj.user_token_path
        obj.id = ''
        obj.parents = []
        await obj.list_drives()
    obj.query_proc = False


class gdriveList(GoogleDriveHelper):
    def __init__(self, client, message):
        self.__token_user = False
        self.__token_owner = False
        self.__client = client
        self.__message = message
        self.__reply_to = None
        self.__time = time()
        self.__timeout = 240
        self.user_id = message.from_user.id
        self.user_dict = user_data.get(self.user_id, {})
        self.drives = []
        self.is_cancelled = False
        self.query_proc = False
        self.item_type = "folders"
        self.event = Event()
        self.user_token_path = f'tokens/{self.user_id}.pickle'
        self.id = ''
        self.parents = []
        self.list_status = ''
        self.items_list = []
        self.iter_start = 0
        self.page_step = 1
        super().__init__()

    @new_thread
    async def __event_handler(self):
        pfunc = partial(id_updates, obj=self)
        handler = self.__client.add_handler(CallbackQueryHandler(
            pfunc, filters=regex('^gdq') & user(self.user_id)), group=-1)
        try:
            await wait_for(self.event.wait(), timeout=self.__timeout)
        except:
            self.id = 'Timed Out. Task has been cancelled!'
            self.is_cancelled = True
            self.event.set()
        finally:
            self.__client.remove_handler(*handler)

    async def __send_list_message(self, msg, button):
        if not self.is_cancelled:
            if self.__reply_to is None:
                self.__reply_to = await sendMessage(self.__message, msg, button)
            else:
                await editMessage(self.__reply_to, msg, button)

    async def get_items_buttons(self):
        items_no = len(self.items_list)
        pages = (items_no + LIST_LIMIT - 1) // LIST_LIMIT
        if items_no <= self.iter_start:
            self.iter_start = 0
        elif self.iter_start < 0 or self.iter_start > items_no:
            self.iter_start = LIST_LIMIT * (pages - 1)
        page = (self.iter_start/LIST_LIMIT) + 1 if self.iter_start != 0 else 1
        buttons = ButtonMaker()
        for index, item in enumerate(self.items_list[self.iter_start:LIST_LIMIT+self.iter_start]):
            orig_index = index + self.iter_start
            if item['mimeType'] == self.G_DRIVE_DIR_MIME_TYPE:
                ptype = 'fo'
                name = item['name']
            else:
                ptype = 'fi'
                name = f"[{get_readable_file_size(float(item['size']))}] {item['name']}"
            buttons.ibutton(name, f'gdq pa {ptype} {orig_index}')
        if items_no > LIST_LIMIT:
            for i in [1, 2, 4, 6, 10, 30, 50, 100]:
                buttons.ibutton(i, f'gdq ps {i}', position='header')
            buttons.ibutton('Previous', 'gdq pre', position='footer')
            buttons.ibutton('Next', 'gdq nex', position='footer')
        if self.list_status == 'gdd':
            if self.item_type == 'folders':
                buttons.ibutton(
                    'Files', 'gdq itype files', position='footer')
            else:
                buttons.ibutton(
                    'Folders', 'gdq itype folders', position='footer')
        if self.list_status == 'gdu' or len(self.items_list) > 0:
            buttons.ibutton('Choose Current Path',
                            'gdq cur', position='footer')
        if self.list_status == 'gdu':
            buttons.ibutton('Set as Default Path',
                            'gdq def', position='footer')
        if len(self.parents) > 1 and len(self.drives) > 1 or self.__token_user and self.__token_owner:
            buttons.ibutton('Back', 'gdq back pa', position='footer')
        if len(self.parents) > 1:
            buttons.ibutton('Back To Root', 'gdq root', position='footer')
        buttons.ibutton('Cancel', 'gdq cancel', position='footer')
        button = buttons.build_menu(f_cols=2)
        msg = 'Choose Path:' + ('\nTransfer Type: <i>Download</i>' if self.list_status ==
                                'gdd' else '\nTransfer Type: <i>Upload</i>')
        if self.list_status == 'gdu':
            default_id = self.user_dict.get('gdrive_id') or config_dict['GDRIVE_ID']
            msg += f"\nDefault Gdrive ID: {default_id}" if default_id else ''
        msg += f'\n\nItems: {items_no}'
        if items_no > LIST_LIMIT:
            msg += f' | Page: {int(page)}/{pages} | Page Step: {self.page_step}'
        msg += f'\n\nItem Type: {self.item_type}\nToken Path: {self.token_path}'
        msg += f'\n\nCurrent ID: <code>{self.id}</code>'
        msg += f"\nCurrent Path: <code>{('/').join(i['name'] for i in self.parents)}</code>"
        msg += f'\nTimeout: {get_readable_time(self.__timeout-(time()-self.__time))}'
        await self.__send_list_message(msg, button)

    async def get_items(self, itype=''):
        if itype:
            self.item_type == itype
        elif self.list_status == 'gdu':
            self.item_type == 'folders'
        try:
            files = self.getFilesByFolderId(self.id, self.item_type)
            if self.is_cancelled:
                return
        except Exception as err:
            if isinstance(err, RetryError):
                LOGGER.info(
                    f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            err = str(err).replace('>', '').replace('<', '')
            self.id = ''
            self.event.set()
            return
        if len(files) == 0 and itype != self.item_type and self.list_status == 'gdd':
            itype = 'folders' if self.item_type == 'files' else 'files'
            self.item_type = itype
            return await self.get_items(itype)
        self.items_list = natsorted(files)
        self.iter_start = 0
        await self.get_items_buttons()

    async def list_drives(self):
        self.service = self.authorize()
        try:
            result = self.service.drives().list(pageSize='100').execute()
        except Exception as e:
            self.id = str(e)
            self.event.set()
            return
        drives = result['drives']
        if len(drives) == 0:
            self.drives = [{'id': 'root', 'name': 'root'}]
            self.parents = [{'id': 'root', 'name': 'root'}]
            self.id = 'root'
            await self.get_items()
        else:
            msg = 'Choose Drive:' + \
                    ('\nTransfer Type: <i>Download</i>' if self.list_status ==
                 'gdd' else '\nTransfer Type: <i>Upload</i>')
            msg += f'\nToken Path: {self.token_path}'
            msg += f'\nTimeout: {get_readable_time(self.__timeout-(time()-self.__time))}'
            buttons = ButtonMaker()
            buttons.ibutton('root', "gdq dr 0")
            self.drives.clear()
            self.parents.clear()
            self.drives = [{'id': 'root', 'name': 'root'}]
            for index, item in enumerate(drives, start=1):
                self.drives.append({'id': item['id'], 'name': item['name']})
                buttons.ibutton(item['name'], f"gdq dr {index}")
            if self.__token_user and self.__token_owner:
                buttons.ibutton('Back', 'gdq back dr', position='footer')
            buttons.ibutton('Cancel', 'gdq cancel', position='footer')
            button = buttons.build_menu(2)
            await self.__send_list_message(msg, button)

    async def choose_token(self):
        if self.__token_user and self.__token_owner:
            msg = 'Choose Token:' + \
                ('\nTransfer Type: Download' if self.list_status ==
                 'gdd' else '\nTransfer Type: Upload')
            msg += f'\nTimeout: {get_readable_time(self.__timeout-(time()-self.__time))}'
            buttons = ButtonMaker()
            buttons.ibutton('Owner Token', 'gdq owner')
            buttons.ibutton('My Token', 'gdq user')
            buttons.ibutton('Cancel', 'gdq cancel')
            button = buttons.build_menu(2)
            await self.__send_list_message(msg, button)
        else:
            self.token_path = 'token.pickle' if self.__token_owner else self.user_token_path
            await self.list_drives()

    async def get_pevious_id(self):
        if self.parents:
            self.parents.pop()
            self.id = self.parents[-1]['id']
            await self.get_items()
        else:
            await self.list_drives()

    async def get_target_id(self, status, token_path=None):
        self.list_status = status
        future = self.__event_handler()
        if token_path is None:
            self.__token_user = await aiopath.exists(self.user_token_path)
            self.__token_owner = await aiopath.exists('token.pickle')
            if not self.__token_owner and not self.__token_user:
                self.event.set()
                return 'token.pickle not Exists!'
            await self.choose_token()
        else:
            self.token_path = token_path
            await self.list_drives()
        await wrap_future(future)
        if self.__reply_to:
            await self.__reply_to.delete()
        if self.token_path != 'token.pickle' and not self.is_cancelled:
            return f'mtp:{self.id}'.replace('>', '').replace('<', '')
        return self.id.replace('>', '').replace('<', '')
