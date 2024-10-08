#!/usr/bin/env bash
set -e

source /etc/profile

# Per form-case/kobo-docker#301, we have changed the uWSGI port to 8001. This
# provides a helpful message to anyone still trying to use port 8000
if [[ "${KOBOCAT_WEB_SERVER,,}" == "uwsgi" ]]
then
    exec $(command -v uwsgi) --uid "${UWSGI_USER}" --gid "${UWSGI_GROUP}" --socket :8000 --wsgi-file "${KOBOCAT_SRC_DIR}/docker/wrong_port_warning.wsgi"
else
    exec gosu "${UWSGI_USER}" "${KOBOCAT_SRC_DIR}/docker/dev_wrong_port_warning.py" 8000
fi
