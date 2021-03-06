from fabric.api import *
from fabric.contrib.files import exists
import os
import sys

def prepare():
    """Setup a fresh virtualenv as well as a few useful directories
    """
    require('hosts')
    require('basedir')
    require('webapp_user')
    #TODO check existence of env first
    sudo(('mkdir -p %(basedir)s/releases; '
          'mkdir -p %(basedir)s/shared; '
          'mkdir -p %(basedir)s/packages; '
          'virtualenv --python=python2.7 %(basedir)s; ') % env)
    with cd('%(basedir)s' % env):
        sudo('chown -R %(webapp_user)s:%(webapp_user)s .' % env)

def upload(rm_local=True):
    """Create an archive from the current Git master branch and upload it."""
    require('version')
    require('basedir')
    require('project')    
    require('git_branch')
    require('local_root')

    filename = '%(version)s.tar.gz' % env
    
    path = os.path.abspath(os.path.join(env.local_root, '../'))
    archive(env.git_branch, filename, path)
    tarfile = os.path.join(path, filename)

    put('%s' % tarfile, 
        '%(basedir)s/packages/' % env, use_sudo=True)
    if rm_local:
        local('rm %s' % tarfile)
    unpack()

def install():
    require('version')
    require('basedir')
    require('project')
    require('pip_requirements')

    install_requirements()
    link_current_version()
    configure()

def init():
    require('basedir')
    require('project')

    with cd('%(basedir)s/releases/current/%(project)s' % env):
        # _vsudo('./manage.py syncdb --noinput --verbosity=1')
        # _vsudo('./manage.py migrate --noinput --verbosity=1')
        # _vsudo('./manage.py collectstatic --noinput')
        with prefix('PATH=%(basedir)s/bin/:PATH' % env):
            _sudo('python manage.py syncdb --noinput --verbosity=1')
            _sudo('python manage.py migrate --noinput --verbosity=1')
            _sudo('python manage.py collectstatic --noinput')

def archive(branch, filename, path='', prefix='', format='tar'):
    if prefix:
        prefix = '--prefix=%s' % prefix

    cmd = ('cd  %(path)s; '
           'git archive --format=%(format)s '
           '%(prefix)s %(branch)s | '
           'gzip > %(filename)s') % locals()
    return local(cmd)

def unpack():
    """Unpack an archive in the packages folder into the releases folder"""
    require('version')
    require('basedir')
    _sudo('mkdir %(basedir)s/releases/%(version)s' % env)
    _sudo(('tar zxf %(basedir)s/packages/%(version)s.tar.gz -C '
         '%(basedir)s/releases/%(version)s') % env)

def install_requirements():
    """Install the required packages from the requirements file using pip."""
    require('version')
    require('basedir')
    require('project')
    require('pip_requirements')

    _install_gdal()
    _install_xapian()
    _install_gunicorn()

    with cd('%(basedir)s' % env):
        _sudo('source ./bin/activate')
        _sudo(('./bin/pip install -r '
               './releases/%(version)s/%(pip_requirements)s') % env)

def link_current_version():
    """Symlink our current version."""
    require('version')
    require('basedir')

    _sudo(('rm %(basedir)s/releases/previous; '
           'mv %(basedir)s/releases/current %(basedir)s/releases/previous; '
           'ln -s %(basedir)s/releases/%(version)s %(basedir)s/releases/current') % env)


def configure(dbname='odekro', dbuser='postgres', dbpass='', dbhost='localhost',
              timezone='Africa/Accra'):
    require('basedir')
    require('version')

    settings=dict(DB_USER=dbuser, DB_NAME=dbname, DB_PASS=dbpass, DB_HOST=dbhost,
                  TIME_ZONE=timezone,
                  SECRET_KEY=_random_chars(50))

    yml_file = '%(basedir)s/releases/%(version)s/conf/general.yml' % env
    
    try:
        _sudo('rm %s' % yml_file)
    except: pass
    
    _sudo('cp %s-example %s' % (yml_file, yml_file))

    cmd1 = '''sed -e "s|%s: '[^\']*'|%s: '%s'|" -i %s %s'''
    for key in settings:
        _sed(cmd1, key, settings[key], yml_file)

    cmd2 = '''sed -e "s|%s: .*|%s: %s|" -i %s %s'''
    settings = dict(COUNTRY_APP='kenya')
    for key in settings:
        _sed(cmd2, key, settings[key], yml_file)


def _sed(cmd, key, value, filepath):
    try:
        # GNU
        _sudo(cmd % (key, key, value, '', filepath))
    except:
        # BSD
        _sudo(cmd % (key, key, value, '""', filepath))

def _install_gdal():
    require('basedir')
    with cd('%(basedir)s' % env):
        _sudo('source ./bin/activate')
        _sudo('./bin/pip install --no-install GDAL')
        try:
            with cd('%(basedir)s/build/GDAL' % env):
                _sudo(('%(basedir)s/bin/python setup.py build_ext'
                       ' --include-dirs=/usr/include/gdal/') % env)
        except: pass
        _sudo('./bin/pip install --no-download GDAL')


def _install_xapian(version='1.2.12'):
    # Thanks to https://gist.github.com/199025
    require('basedir')

    sudo('aptitude install -y zlib1g-dev g++')

    REP = 'http://oligarchy.co.uk/xapian/%s/' % version

    with cd('%(basedir)s' % env):
        _sudo('source ./bin/activate')
        # _sudo('export VENV=$VIRTUAL_ENV')
        with cd ('%(basedir)s/packages' % env):
            for pkg in ('core', 'bindings'):
                tarfile = 'xapian-%s-%s.tar.gz' % (pkg, version)
                if not exists(tarfile):
                    _sudo('wget %s/%s' % (REP, tarfile))
                if not exists('xapian-%s-%s' % (pkg, version)):
                    _sudo('tar xzvf %s' % tarfile)
        with cd('%s/packages/xapian-core-%s' % (env.basedir, version)):
            _sudo(('PYTHON=%(basedir)s/bin/python '
                   './configure --prefix=%(basedir)s && '
                   'make && '
                   'make install' % env))

        _sudo('export LD_LIBRARY_PATH=%(basedir)s/lib' % env)
        
        # http://trac.xapian.org/ticket/409

        with cd('%s/packages/xapian-bindings-%s' % (env.basedir, version)):
            _sudo(('PYTHON=%(basedir)s/bin/python '
                   'LD_LIBRARY_PATH=%(basedir)s/lib '
                   './configure XAPIAN_CONFIG=%(basedir)s/bin/xapian-config '
                   '--prefix=%(basedir)s --with-python && '
                   'make && '
                   'make install') % env)

def _install_gunicorn():
    """ force gunicorn installation into your virtualenv, even if it's installed globally.
    for more details: https://github.com/benoitc/gunicorn/pull/280 """
    _vsudo('pip install -I gunicorn')
    
def _random_chars(size):
    """Generates a string of random characters."""
    import random; 
    CHARS = "abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)"
    return "".join([random.choice(CHARS) for i in range(size)])

def _vsudo(cmd):
    # activate = 'source %(basedir)s/bin/activate' % env
    # return _sudo('%s && %s' % (activate , cmd))
    with prefix('PATH=%(basedir)s/bin/:PATH' % env):
        return _sudo(cmd)

def _sudo(cmd):
    require('webapp_user')
    return sudo(cmd, user='%(webapp_user)s' % env)



# def activate_application(version=None):
#     """Add the virtualhost file to apache."""
#     if not version:
#         require('version', provided_by=[deploy, setup])
#     else:
#         env.version = version
#     sudo(('cp %(basedir)s/releases/%(version)s/%(project)s/%(vhost_file)s '
#           '%(apache_sites)s/%(project)s' % env))
#     activate_site('%(project)s' % env)

# def deactivate_application():
#     deactivate_site('%(project)s' % env)

