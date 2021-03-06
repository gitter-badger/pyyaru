# -*- coding: utf-8 -*-
"""pyyaru реализует Python-интерфейс к API блог-сервиса Я.ру http://wow.ya.ru.

Репозитарий проекта: http://github.com/idlesign/pyyaru

"""

import logging
import os
import datetime
import httplib
import urlparse
from collections import defaultdict
from lxml import etree
from __init__ import VERSION

LOG_LEVEL = logging.ERROR

API_SERVER = 'https://api-yaru.yandex.ru'

URN_PREFIX = 'urn:ya.ru:'

# Соотношения URN-типов и объектов
URN_TYPES = {
    'person': 'yaPerson',
    'persons': 'yaPersons',
    'entry': 'yaEntry',
    'entries': 'yaEntries',
    'club': 'yaClub',
    'clubs': 'yaClubs',
   }

NAMESPACES = {
    'a': 'http://www.w3.org/2005/Atom',
    'y': 'http://api.yandex.ru/yaru/',
    'thr': 'http://purl.org/syndication/thread/1.0',
}

ACCESS_TOKEN = None

# Если в директории библиотеки лежит файл token в формате JSON, полученный
# в ходе авторизации OAuth 2 и ACCESS_TOKEN не задан, то берем реквизиты из этого файла.
token_filepath = '%s/token' % os.path.dirname(os.path.realpath(__file__))
if os.path.exists(token_filepath) and ACCESS_TOKEN is None:
    token_file = open(token_filepath, 'rb')
    token = eval(token_file.read())
    if isinstance(token, dict):
        ACCESS_TOKEN = token['access_token']
    token_file.close()

logging.basicConfig(level=LOG_LEVEL, format="** %(asctime)s - %(name)s - %(levelname)s\n%(message)s\n")


class yaError(Exception):
    """Базовый класс ошибок модуля."""
    pass


class yaObjectTypeMismatchError(yaError):
    """Ошибка несоответствия класса pyyaru типу данных, заявленному ресурсом."""
    pass


class yaEntryTypeUnknownError(yaError):
    """Ошибка неопознанного типа публикации (yaEntry)."""
    pass


class yaEntryAccessUnknownError(yaError):
    """Ошибка неопознанного уровня доступа для публикации (yaEntry)."""
    pass


class yaPersonInclubRoleUnkwnownError(yaError):
    """Ошибка неопознанной роли пользователя в клубе (yaPerson)."""
    pass


class yaOperationError(yaError):
    """Ошибка действия, произведённого над ресурсом."""
    pass


class yaUnsupportedMethodError(yaError):
    """Ошибка вызова неподдерживаемого метода."""
    pass


class yaInternalServerError(yaError):
    """Внутрення ошибка на сервере, предоставляющем ресурс."""
    pass


class yaResourceNotFoundError(yaError):
    """Ошибка отсутствия запрошенного ресурса."""
    pass


class yaBadRequestError(yaError):
    """Ошибка в запросе к серверу."""
    pass


class yaAccessForbiddenError(yaError):
    """Ошибка уровня доступа к данным."""
    pass


class Logger(object):
    """Класс логирования."""

    def __init__(self):
        self._logger = None

    def __get__(self, instance, owner):
        if self._logger is None:
            self._logger = logging.getLogger(owner.__module__ + "." + owner.__name__)

        return self._logger


class yaBase(object):
    """Класс, осуществляющий базовое представление ресурса Я.ру в виде объекта pyyaru."""

    __logger = Logger()

    def __init__(self, id, **kwargs):
        self.__parsed = False
        self.id = id
        self._type = self.__class__.__name__.lstrip('ya').lower()

        if 'attributes' in kwargs and isinstance(kwargs['attributes'], dict):
            for key in kwargs['attributes'].keys():
                setattr(self, key, kwargs['attributes'][key])

    def __getattr__(self, name):
        """При обращении к любому из свойств объекта, в случае, если данные
        еще не были загружены с ресурса, происходит загрузка.

        """
        if self.id is not None and self.__parsed == False:
            self.get()

        try:
            return self.__dict__[name]
        except KeyError as e:
            raise AttributeError(e)

    def __str__(self):
        """Трансляцией объекта в строку является идентификатор объекта."""
        return '%s' % self.id

    def __iter__(self):
        """Реализует возможность прохода по всем свойствам объекта в
        конструкции for key, value in ...
        Вернет кортеж, где первый элемент является именем свойства класса,
        а второй значением свойства.

        """
        for attribute in self.__dict__:
            if not attribute.startswith('_'):
                yield (attribute, self.__dict__[attribute])

    def _parse(self, resource_data):
        """Запускает механизм парсинга xml, полученного с ресурса.
        Дерево xml транслирует в свойства объекта.

        """
        root = etree.fromstring(resource_data[1])
        for attrib in self.__parse_recursion(root):
            self.__dict__[attrib[0]] = attrib[1]

        self.__dict__['links'] = {}
        for link in root.xpath('/*/a:link | /*/y:link', namespaces=NAMESPACES):
            self.__dict__['links'][link.attrib['rel']] = link.attrib['href']

        self.__parsed = True

    def __parse_recursion(self, root, usedict=None):
        """Итератор, проходящий по xml дереву и составляющий списки,
        которые в последствии станут свойствами объекта.
        Выбрасывает пары ключ-значение.

        """
        for el in root:

            nsmap = el.nsmap[None]

            if 'y' in el.nsmap and el.tag.find('yandex') > -1:
                nsmap = el.nsmap['y']

            tagname = el.tag.replace('{%s}' % nsmap, '')

            if tagname == 'link':
                # ссылки обрабатываем отдельно, загоняя их в "тэг" links
                tagname = 'links'
                tagcontent = [el.attrib['rel'], el.attrib['href']]
            else:
                if len(el) > 0:
                    usedict = defaultdict(list)
                    for subel in self.__parse_recursion(el, usedict):
                        if subel[0] == 'links':
                            # из вложенных элементов типа link формируем словарь
                            if subel[0] not in usedict:
                                usedict[subel[0]] = {}
                            usedict[subel[0]][subel[1][0]] = subel[1][1]
                        else:
                            if isinstance(subel[1], basestring):
                                usedict[subel[0]] = subel[1]
                            else:
                                usedict[subel[0]].append(subel[1])
                    tagcontent = usedict
                else:
                    tagcontent = el.text

                if isinstance(tagcontent, basestring):
                    tagcontent = tagcontent.strip()
                    if tagcontent == '':
                        tagcontent = None

            yield [tagname, tagcontent]

    def get(self):
        """Запрашивает объект с сервера и направляет его в парсер."""
        resource_data = yaResource(self.id).get()
        if resource_data is not None:
            # FIXME: API багфикс (не задан тип в Content-type) для entries
            if resource_data[0] == self._type or self._type == 'entries':
                self._parse(resource_data)
            else:
                raise yaObjectTypeMismatchError('Data type "%s" defined by resource mismatches pyyaru object "%s"'
                       % (resource_data[0], self.__class__.__name__))
        return self

    def save(self, target_url=None):
        """Используется для создания нового ресурса, либо обновляния имеющегося.
        В случае удачного свершения свойство вернёт объект.

        """
        data = self._compose()

        if self.id is None:
            resource_data = yaResource(target_url).create(data, self._content_type)
            if not resource_data[2]:
                raise yaOperationError('Unable to create resource at "%s".' % target_url)
        else:
            resource_data = yaResource(self.links['edit']).update(data, self._content_type)
            if not resource_data[2]:
                raise yaOperationError('Unable to update resource at "%s".' % self.links['edit'])

        if resource_data is not None and resource_data[2]:
            self._parse(resource_data)

        return self

    def delete(self):
        """Используется для удаления ресурса.
        В случае удачного свершения вернёт объект с полем id выставленным в None.

        """
        if self.id is not None:
            try:
                resource_data = yaResource(self.links['edit']).delete()
            except KeyError:
                raise yaOperationError('Unable to delete resource: edit resource link is undefined.')

            if not resource_data[2]:
                raise yaOperationError('Unable to delete resource at "%s".' % self.links['edit'])
            else:
                self.id = None

        return self


class yaCollection(yaBase):
    """Класс описывает ресурсы-коллекции (н.п. список друзей, список клубов, список публикаций).
    В случае удачного свершения, свойство objects объекта класса будет заполнено
    объектами соответствующего типа, каждый из которых описывает одну сущность из списка.
    Свойство objects является списком.

    """

    objects = []

    def _parse(self, resource_data):
        """Для получения списка объектов дополняем механизм разбора xml, определенный
        в супер-классе yaBase.

        """
        super(yaCollection, self)._parse(resource_data)
        root = etree.fromstring(resource_data[1])
        ns = 'y'
        tagname = self._type.rstrip('s')
        if self._type == 'entries':
            ns = 'a'
            tagname = tagname.replace('ie', 'y')

        for item in root.xpath('//%s:%s' % (ns, tagname), namespaces=NAMESPACES):
            obj = globals()['ya%s' % tagname.capitalize()](None)
            resource_data = [item.tag, etree.tostring(item, xml_declaration=True, encoding='utf-8')]
            obj._parse(resource_data)
            self.objects.append(obj)

        if tagname in self.__dict__:
            del(self.__dict__[tagname])

    def __len__(self):
        """Возвращает количество вложенных объектов (содержащихся в self.objects)."""
        return len(self.objects)

    def save(self):
        """Для коллекций метод не поддерживается."""
        raise yaUnsupportedMethodError('"save" method is unsupported by collections.')

    def delete(self):
        """Для коллекций метод не поддерживается."""
        raise yaUnsupportedMethodError('"delete" method is unsupported by collections.')

    def more(self):
        """Запрашивает с сервера следующую порцию объектов.
        Возвращает список новых объектов, при этом дополняет список objects текущего
        класса-коллекции новыми.
        В случае, если заявленный ресурс-коллекция со следующей порцией не описывает
        объектов, вернёт False.

        """
        if 'links' in self.__dict__ and 'next' in self.links:
            more_items = globals()[self.__class__.__name__](self.links['next']).get()
            if len(more_items.objects) > 0:
                self.objects += more_items.objects
                self.links['next'] = more_items.links['next']
                return more_items.objects

        return False

    def iter(self):
        """Итератор осуществляет проход про всем элементам, которые описывает
        ресурс-коллекция, задействуя при этом постраничное перемещение more().
        Выбрасывает объект, созданный на основе очередного элемента.

        """
        for obj in self.objects:
            yield obj

        while True:
            more_items = self.more()
            if more_items:
                for obj in more_items:
                    yield obj
            else:
                break


class yaPerson(yaBase):
    """Класс описывает ресурс пользователя Я.ру (профиль)."""

    _content_type = 'application/x-yaru+xml; type=person;'
    _inclub_roles = ['member', 'moderator', 'owner']

    def __getitem__(self, key):
        """Разрешает обращение к свойствам объекта в нотации self[key].
        Для максимальной похожести обращения к yaPerson с обращением
        к свойству author вложенных объектов yaEntries.

        """
        try:
            return self.__dict__[key]
        except KeyError as e:
            raise AttributeError(e)

    def change_name(self, new_name):
        """Смена имени пользователя. Под капотом происходит создание
        новой записи типа 'rename'.

        """
        raise NotImplementedError('This method is not yet implemented.')

    def publish_entry(self, entry):
        """Публикует указанный объект yaEntry в дневнике пользователя."""
        if isinstance(entry, yaEntry):
            return entry.save(self.links['posts'])
        else:
            raise yaError('Entry parameter is not an object of yaEntry type.')

    def set_status(self, status, access='public', comments_disabled=False):
        """Смена настроения. Под капотом происходит создание
        новой записи типа 'status'.

        """
        entry = yaEntry(
            attributes={
                'type': 'status',
                'content': status,
                'access': access,
                'comments_disabled': comments_disabled,
            }
            )

        return self.publish_entry(entry)

    def _make_related_entry(self, resource_type, target, action, entry_text, access, comments_disabled):
        """Формирует и пытается создать новую запись заданного типа,
        описывающую отношение между объектами (ресурсами),
        н.п. вступление пользователя в клуб (пользователь-клуб), начало
        дружбы (пользователь-пользователь) и т.д.

        """
        cl = globals()[URN_TYPES[resource_type]]

        target_id = target

        if isinstance(target, cl):
            target_id = target.id

        if not target_id.startswith('%s%s' % (URN_PREFIX, resource_type)):
            target = cl(target_id).get()
            target_id = target.id

        entry = yaEntry(
            attributes={
                'type': action,
                'content': entry_text,
                'access': access,
                'comments_disabled': comments_disabled,
                'meta': {resource_type: {'id': target_id}}
            }
            )

        return self.publish_entry(entry)

    def friend(self, whom, entry_text='', access='public', comments_disabled=False):
        """Подружиться. Под капотом происходит создание
        новой записи типа 'friend'.

        -- whom - может содержать идентификатор пользователя,
                  с которым заводится дружба, URL ресурса этого пользователя,
                  либо объект yaPerson

        """
        return self._make_related_entry('person', whom, 'friend', entry_text, access, comments_disabled)

    def unfriend(self, whom, entry_text='', access='public', comments_disabled=False):
        """Раздружиться. Под капотом происходит создание
        новой записи типа 'unfriend'.

        -- whom - может содержать идентификатор пользователя,
                  с которым нужно перестать дружить, URL ресурса этого пользователя,
                  либо объект yaPerson

        """
        return self._make_related_entry('person', whom, 'unfriend', entry_text, access, comments_disabled)

    def join_club(self, club, entry_text='', access='public', comments_disabled=False):
        """Вступить в клуб. Под капотом происходит создание
        новой записи типа 'join'.

        -- club - может содержать идентификатор клуба,
                  в который нужно вступить, URL ресурса этого клуба,
                  либо объект yaClub

        """
        return self._make_related_entry('club', club, 'join', entry_text, access, comments_disabled)

    def leave_club(self, club, entry_text='', access='public', comments_disabled=False):
        """Покинуть клуб. Под капотом происходит создание
        новой записи типа 'unjoin'.

        -- club - может содержать идентификатор клуба,
                  из которого нужно уйти, URL ресурса этого клуба,
                  либо объект yaClub

        """
        return self._make_related_entry('club', club, 'unjoin', entry_text, access, comments_disabled)

    def clubs(self, where_role='member'):
        """Запрашивает с сервера клубы, к которым пользователь имеет отношение,
        и возвращает их в виде объекта-контейнера yaClubs.
        Параметр where_role задаёт фильтр роли пользователя в клубе.
        Возможные значения: 'member', 'moderator', 'owner'.

        """
        if not where_role in self._inclub_roles:
            raise yaPersonInclubRoleUnkwnownError('Supplied role "%s" is unknown. Valid choices: %s.' % (where_role, self._inclub_roles))

        return yaClubs(self.links[where_role + '_of_clubs']).get()

    def friends(self):
        """Запрашивает с сервера друзей пользователя и возвращает их
        в виде объекта-контейнера yaPersons.

        """
        return yaPersons(self.links['friends']).get()

    def entries(self, by_type='ANY'):
        """Запрашивает с сервера публикации пользователя и возвращает их
        в виде объекта-контейнера yaEntries.
        Параметр by_type позволяет запросить публикации определенного типа
        (см. список _TYPES класса yaEntry).

        """
        return yaEntries(self.links['posts'], by_type).get()

    def friends_entries(self, by_type='ANY'):
        """Запрашивает с сервера публикации друзей пользователя и возвращает их
        в виде объекта-контейнера yaEntries.
        Параметр by_type позволяет запросить публикации определенного типа
        (см. список _TYPES класса yaEntry).

        """
        return yaEntries(self.links['friends_posts'], by_type).get()


class yaPersons(yaCollection):
    """Класс описывает ресурс коллекции пользователий (н.п. список друзей).
    В случае удачного свершения, свойство objects объекта класса будет заполнено
    объектами класса yaPerson, каждый из которых описывает одного пользователя
    из коллекции.
    Свойство objects является списком.

    """
    _content_type = 'application/x-yaru+xml; type=persons;'


class yaClub(yaBase):
    """Класс описывает ресурс клуба."""

    _content_type = 'application/x-yaru+xml; type=club;'

    def publish_entry(self, entry):
        """Публикует указанный объект yaEntry в клубе."""
        if isinstance(entry, yaEntry):
            return entry.save(self.links['posts'])
        else:
            raise yaError('Entry parameter is not an object of yaEntry type.')

    def add_news(self, news_text):
        """Публикация новости клуба. Под капотом происходит создание
        новой записи типа 'news'.

        """
        raise NotImplementedError('This method is not yet implemented.')

    def set_rules(self, rules):
        """Публикация правил клуба. Под капотом происходит создание
        новой записи типа 'rules'.

        """
        raise NotImplementedError('This method is not yet implemented.')

    def join(self, entry_text='', access='public', comments_disabled=False):
        """Вступление в клуб. Под капотом происходит обращение
        к ресурсу /me/ и создание новой записи типа 'join'.

        """
        me = yaPerson('/me/').get()
        me.join_club(self, entry_text, access, comments_disabled)

    def leave(self, entry_text='', access='public', comments_disabled=False):
        """Уход из клуба. Под капотом происходит обращение
        к ресурсу /me/ и создание новой записи типа 'unjoin'.

        """
        me = yaPerson('/me/').get()
        me.leave_club(self, entry_text, access, comments_disabled)

    def entries(self, by_type='ANY'):
        """Запрашивает с сервера публикации клуба и возвращает их
        в виде объекта-контейнера yaEntries.
        Параметр by_type позволяет запросить публикации определенного типа
        (см. список _TYPES класса yaEntry).

        """
        return yaEntries(self.links['posts'], by_type).get()

    def members(self):
        """Запрашивает с сервера членов клуба и возвращает их
        в виде объекта-контейнера yaPersons.

        """
        return yaPersons(self.links['club_members']).get()


class yaClubs(yaCollection):
    """Класс описывает ресурс коллекции клубов (н.п. те, в которых состоит пользователь.
    В случае удачного свершения, свойство objects объекта класса будет заполнено
    объектами класса yaClub, каждый из которых описывает один клуб из коллекции.
    Свойство objects является списком.

    """
    _content_type = 'application/x-yaru+xml; type=clubs;'


class yaEntry(yaBase):
    """Класс описывает ресурс сообщения (публикации)."""

    __logger = Logger()

    _content_type = 'application/atom+xml; type=entry;'

    _TYPES = [
        # Записи
        'link',             # Ссылка
        'text',             # Текст
        'complaint',        # Жалоба
        'photo',            # Фото
        'video',            # Видео
        'poll',             # Опрос
        'wishlist',         # Желание
        'congratulation',   # Поздравление
        'description',      # Обращение к гостям
        # Яндекс.Ответы
        'question',         # Задать вопрос
        'answer',           # Ответить на вопрос
        # Друзья
        'friend',           # Подружиться
        'unfriend',         # Раздружиться
        # Яндекс.Маркет
        'model_grade',      # Оценка товара
        'model_opinion',    # Отзыв о товаре
        'shop_grade',       # Оценка магазина
        'shop_opinion',     # Отзыв о магазине
        # Пользователь
        'status',           # Изменить настроение
        'userpic',          # Изменить аватар
        'rename',           # Изменить имя
        # Клуб
        'news',             # Новость
        'rules',            # Правила
        'join',             # Присоединиться к клубу
        'unjoin',           # Уйти из клуба

        # Прочее
        'activity_fotki',   # Не используется
        'activity_video',   # Не используется
        'offline',          # Не используется. Куда все идут.
        'opinion',          # ?
        'premoderated',     # ?
        ]

    _ACCESS_LEVELS = [
        'public',  # всем
        'private',  # только мне
        'friends',  # друзьям
        ]

    _comments_disabled = False
    _access = 'private'
    _entry_type = 'text'

    def __init__(self, id=None, **kwargs):
        """Метод перекрывает родительский для возможности создания нового
        объекта yaEntry (без указания id).

        """
        super(self.__class__, self).__init__(id, **kwargs)

    def make_comment(self, entry_content, entry_type='text', access='public', comments_disabled=False):
        """Добавляет комментарий указанного типа к текущей записи."""
        entry = yaEntry(
            attributes={
                'type': entry_type,
                'content': entry_content,
                'access': access,
                'comments_disabled': comments_disabled,
            }
        )
        entry.save(self.links['comments'])
        return entry

    def _set_type(self, entry_type):
        """Устанавливает тип записи, сверяясь со списком разрешенных типов."""
        if entry_type in self._TYPES:
            self._entry_type = entry_type
        else:
            raise yaEntryTypeUnknownError('Unable to set unrecognized "%s" entry type.' % entry_type)

    def _get_type(self):
        """Тип записи.
        Возможные значения хранятся в списке _TYPES.

        """
        return self._entry_type
    type = property(_get_type, _set_type)  # Методы выше определяют свойство type.

    def _set_access(self, access_level):
        """Устанавливает уровень доступа к записи, сверяясь со списком разрешенных уровней."""
        if access_level in self._ACCESS_LEVELS:
            self._access = access_level
        else:
            raise yaEntryAccessUnknownError('Unable to set unrecognized %s" entry access type.' % access_level)

    def _get_access(self):
        """Уровень доступа к записи.
        Возможные значения хранятся в списке _ACCESS_LEVELS.

        """
        return self._access
    access = property(_get_access, _set_access)  # Методы выше определяют свойство access.

    def _set_comments_disabled(self, disabled):
        """Устанавливает флаг отключения возможности комментирования записи."""
        self._comments_disabled = disabled

    def _get_comments_disabled(self):
        """Флаг отключения возможности комментирования записи.
        Возможные значения: true, false.

        """
        return self._comments_disabled
    comments_disabled = property(_get_comments_disabled, _set_comments_disabled)  # Методы выше определяют свойство comments_disabled.

    def _parse(self, resource_data):
        """Парсит xml-документ с учетом специфики ресурса entry.
        Утилизирует парсер класса-родителя.

        """
        super(self.__class__, self)._parse(resource_data)

        if 'access' in self.__dict__:
            self.access = self.__dict__['access']
            del(self.__dict__['access'])
        else:
            self.access = 'public'

        if 'comments-disabled' in self.__dict__:
            del(self.__dict__['comments-disabled'])
            self.comments_disabled = True
        else:
            self.comments_disabled = False

        try:
            del(self.__dict__['category'])
        except KeyError:
            pass

        if 'original' in self.__dict__:
            self.original = self.__dict__['original']
        else:
            self.original = None

        if self.__dict__.get('updated') is not None:
            self.__dict__['updated'] = datetime.datetime.strptime(self.__dict__['updated'], '%Y-%m-%dT%H:%M:%SZ')
        root = etree.fromstring(resource_data[1])
        self.__dict__['categories'] = []
        for category in root.xpath('/*/a:category', namespaces=NAMESPACES):
            if category.attrib['scheme'] == 'urn:ya.ru:posttypes':
                self.type = category.attrib['term']
            else:
                self.__dict__['categories'].append(category.attrib['term'])

        if 'content' not in self.__dict__ or self.content is None:
            self.content = ''
        else:
            self.content = self._html_unescape(self.content)

    def _compose_recursion(self, root, namespace, property_name, property_value):
        """Рекурсивно собирает ветку xml документа на основе данных словаря."""
        if isinstance(property_value, basestring):
            property_value = unicode(property_value)
            etree.SubElement(root, namespace + property_name).text = property_value
        elif isinstance(property_value, dict):
            xml = etree.SubElement(root, namespace + property_name)
            for element in property_value:
                self._compose_recursion(xml, namespace, element, property_value[element])

    def _compose(self):
        """Компонует xml-документ для публикации на ресурсе."""

        ns_a = '{%s}' % NAMESPACES['a']
        ns_y = '{%s}' % NAMESPACES['y']

        xml = etree.Element(ns_a + 'entry', nsmap={None: NAMESPACES['a'], 'y': NAMESPACES['y']})
        etree.SubElement(xml, ns_a + 'category', term=self.type, scheme=URN_PREFIX + 'posttypes')
        etree.SubElement(xml, ns_y + 'access').text = self.access

        if self.comments_disabled:
            etree.SubElement(xml, ns_y + 'comments-disabled')

        # FIXME: API не даёт возможности угадать uid в схеме
        #for category in self.categories:
        #    etree.SubElement(xml, ns_a+'category', term=category, scheme='https://api-yaru.yandex.ru/person/{uid}/tag')

        for property_name, property_value in self:
            if isinstance(property_value, basestring):
                if property_name == 'content':
                    property_value = self._html_escape(property_value)
                property_value = unicode(property_value.decode('utf-8'))
                etree.SubElement(xml, ns_a + property_name).text = property_value
            elif isinstance(property_value, dict):
                if property_name == 'meta':  # Словари с метаданными обрабатываем рекурсивно
                    self._compose_recursion(xml, ns_y, property_name, property_value)

        xml = etree.tostring(xml, encoding='utf-8', pretty_print=True, xml_declaration=True)
        self.__logger.debug('Composed XML:\n%s\n%s%s' % ('-----' * 4, xml, '____' * 25))

        return xml

    def _html_escape(self, html):
        """Готовит HTML для помещения в XML."""
        return html.replace('<', '&lt;')

    def _html_unescape(self, text):
        """Восстанавливает HTML из XML."""
        return text.replace('&amp;', '&').replace('&lt;', '<')


class yaEntries(yaCollection):
    """Класс описывает ресурс коллекции публикаций (н.п. список постов пользователя).
    В случае удачного свершения, свойство objects объекта класса будет заполнено
    объектами класса yaEntry, каждый из которых описывает одну публикацию
    из коллекции.
    Свойство objects является списком.

    """

    _content_type = 'application/atom+xml;'

    def __init__(self, id, by_type='ANY', **kwargs):
        """Метод перекрывает родительский для возможности указания
        типа данных yaEntry.
        Фильтрация по типу данных поддерживается только в случае, если
        задан полноценный URL.

        """
        if by_type != 'ANY':
            if id.startswith('http'):
                id = '%s%s/' % (id, by_type)
            else:
                self.__logger.warning("Attribute 'by_type' set to '%s' for non-http id '%s', thus will be ignored." % (by_type, id))

        super(self.__class__, self).__init__(id, **kwargs)


class yaResource(object):
    """Класс получает абстрактный ресурс Я.ру и/или создает на его основе объект pyyaru."""

    __logger = Logger()

    def __init__(self, resource_name):
        """Получая на вход имя ресура, определяет для него подхоящий URL.

        Понимает следующие виды имён:
        1. Полноценный URL (н.п. https://api-yaru.yandex.ru/person/153990/);
        2. ya-идентификатор URN (н.п. urn:ya.ru:person/153990);
        3. URI (н.п. /me/).

        """
        self.__logger.debug('Resource defined as "%s".' % resource_name)

        resource_name = resource_name.lstrip('/')
        url = resource_name
        if not resource_name.startswith('http'):
            if resource_name.startswith(URN_PREFIX):
                url = '%s/resource/?id=%s' % (API_SERVER, resource_name)
            else:
                url = '%s/%s' % (API_SERVER, resource_name)

        self.url = url

    def __make_request(self, connection, request_method, request_url, data, headers):
        """Производит запросы к серверу в рамках одного соединения.
        Рекурсивно проходит перенаправления.

        """
        parsed_url = urlparse.urlparse(request_url)
        request_url = parsed_url.path
        query_string = parsed_url.query
        if query_string != '':
            request_url = request_url + '?' + query_string
        connection.request(request_method, request_url, data, headers)
        response = connection.getresponse()
        if response.status in (301, 302, 303):
            location = response.getheader('Location')
            self.__logger.info('Redirected to: %s' % location)
            response.read()  # Непременно прочтем ответ перед следующим запросом
            response = self.__make_request(connection, request_method, location, data, headers)
        return response

    def __open_url(self, data=None, request_method="GET", content_type=None):
        """Открывает URL, опционально используя токен авторизации.

        Реализована упрощенная схема, без взаимодействия с OAuth-сервером.
        Для аутентификации необходимо задать ACCESS_TOKEN равным токену,
        полученному на странице
        https://oauth.yandex.ru/authorize?client_id=25df5dd8e3064e188fbbf56f7c667d5f&response_type=code
        Внимание: для получения токена по приведенному ниже адресу
        необходимо быть авторизованным на Яндексе.

        Полученный файл (token) можно положить рядом с pyyaru.py, в таком случае
        реквизиты будут взяты из него автоматически.

        Вернёт кортеж из типа ресурса, полученных с него данных и флага успешности запроса, либо None.

        """
        url = self.url
        headers = {'User-Agent': 'pyyaru %s' % '.'.join(map(str, VERSION))}

        if content_type is not None:
            headers['Content-Type'] = '%s charset=utf-8' % content_type

        if ACCESS_TOKEN is not None:
            headers.update({'Authorization': 'OAuth ' + ACCESS_TOKEN})

        self.__logger.info('Opening URL "%s" with "%s"...' % (url, headers))

        resource_data = None
        try:
            parsed_url = urlparse.urlparse(url)
            connection = httplib.HTTPConnection(parsed_url.netloc)
            if LOG_LEVEL == logging.DEBUG:
                connection.set_debuglevel(1)
            response = self.__make_request(connection, request_method, url, data, headers)
            resource_data = response.read()
            connection.close()
        except httplib.HTTPException as e:
            self.__logger.error('Failed to open "%s".\n Error: "%s"' % (url, e))
            raise

        successful = False

        if response.status == 400:
            error_text = 'Bad request. Check it up for malformed data\n%s\n%s\n%s.' % ('-----' * 4, data, '____' * 25)
            self.__logger.error(' ' + error_text)
            raise yaBadRequestError(error_text)
        if response.status == 403:
            error_text = 'Access to "%s" is forbidden.' % url
            self.__logger.error(' ' + error_text)
            raise yaAccessForbiddenError(error_text)
        elif response.status == 404:
            error_text = 'Requested resource "%s" is not found.' % url
            self.__logger.error(' ' + error_text)
            raise yaResourceNotFoundError(error_text)
        elif response.status == 500:
            error_text = 'Internal server error occurred while opening %s with %s.' % (url, headers)
            self.__logger.error(' ' + error_text)
            raise yaInternalServerError(error_text)
        elif 200 <= response.status < 300:
            successful = True

        if resource_data is not None:
            if resource_data != '':
                self.__logger.debug('Response Body:\n%s\n%s\n%s' % ('-----' * 4, resource_data, '____' * 25))

            resource_type = None

            for ctype_data in response.getheader('Content-Type').split(';'):
                type_index = ctype_data.rfind('type')
                if type_index > -1:
                    resource_type = ctype_data[type_index + 5:]

            resource_data = (resource_type, resource_data, successful)

        return resource_data

    def get(self):
        """Забирает данные ресурса."""
        return self.__open_url()

    def create(self, data, content_type):
        """Отсылает запрос на создание ресурса."""
        return self.__open_url(data, 'POST', content_type)

    def delete(self):
        """Отсылает запрос на удаление ресурса."""
        return self.__open_url(request_method='DELETE')

    def update(self, data, content_type):
        """Отсылает запрос на модификацию ресурса."""
        return self.__open_url(data, 'PUT', content_type)

    def get_object(self):
        """Забирает данные ресура и, по возможности, преобразует ресурс
        в подходящий ya-объект.

        """
        obj = None
        resource_data = self.get()

        if resource_data is not None:
            resource_type = resource_data[0]

            if resource_type in URN_TYPES.keys():
                self.__logger.debug('Resource type "%s" is a valid resource. Now spawning the appropriate object "%s".' % (resource_type, URN_TYPES[resource_type]))
                obj = globals()[URN_TYPES[resource_type]](None)
                obj._parse(resource_data)
            elif resource_type is None:
                self.__logger.warning('Resource type is none')
            else:
                self.__logger.error('Resource type "%s" is unknown' % resource_type)

        return obj
