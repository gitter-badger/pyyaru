pyyaru — Python-интерфейс для API блог-сервиса ya.ru
====================================================
http://github.com/idlesign/pyyaru

.. image:: https://pypip.in/d/pyyaru/badge.png
        :target: https://crate.io/packages/pyyaru

Интерфейс можно использвать для написания собственных Я.ру-клиентов.

* pyayru предназначен для разработчиков.
* pyyaru переплюнул API Я.ру и находится в стадии глубокой альфы.
* pyyaru не умеет делать того, чего не умеет делать API Я.ру и даже больше.

Простой пример использования::

    # Получаю свой профиль.
    me = pyyaru.yaPerson('/me/').get()

    # Узнаю своё имя.
    name = me.name

    # А вот ссылка на мой аватар.
    avatar = me.links['userpic']

    # Сменю своё настроение.
    me.set_status("Играю с pyyaru.")

    # Погляжу, какие настроения у друзей.
    friends_statuses = me.friends_entries('status')
    for status_entry in friends_statuses.objects:
        print '%s говорит: "%s".' % (status_entry.author['name'] , status_entry.content)

    # Вспомню, в каких клубах состою.
    my_clubs = me.clubs()
    for club in my_clubs.iter():
        print club.name

Документация к библиотеке в формате reStructuredText находится в директории docs/.
Для сборки документации используйте команду 'make <форматсборки>' (требует python-sphinx).

Желающие могут воспользоваться документацией с ресурса ReadTheDocs - http://readthedocs.org/docs/pyyaru/en/latest/

