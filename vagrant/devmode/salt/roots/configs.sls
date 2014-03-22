carbon.conf:
  file:
    - copy
    - user: vagrant
    - name: /home/vagrant/calamari/env/conf/carbon.conf
    - source: /home/vagrant/calamari/env/conf/carbon.conf.example
  require:
    - sls: virtualenv

storage-schemas.conf:
  file:
    - copy
    - user: vagrant
    - name: /home/vagrant/calamari/env/conf/storage-schemas.conf
    - source: /home/vagrant/calamari/env/conf/storage-schemas.conf.example
  require:
    - sls: virtualenv

storage_log_webapp:
  file:
    - directory
    - user: vagrant
    - makedirs: true
    - name: /home/vagrant/calamari/env/storage/log/webapp
  require:
    - sls: virtualenv

storage:
  file:
    - directory
    - user: vagrant
    - makedirs: true
    - name: /home/vagrant/calamari/env/storage
  require:
    - sls: virtualenv

log_storage:
  file:
   - directory
   - user: vagrant
   - makedirs: true
   - name: /home/vagrant/calamari/dev/var/log/calamari
  require:
   - sls: virtualenv

{% for config in ('calamari',
                'cthulhu') %}

log_rotate_configs_{{ config }}:
   file:
    - copy
    - user: vagrant
    - name: /etc/logrotate.d/{{ config }}
    - source: /home/vagrant/dev/etc/logrotate.d/{{ config }}
   require:
    - sls: build-deps

{% endfor %}