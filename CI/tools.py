from __future__ import print_function

import os

from tasks import (
    Task,
    TaskEnvironment,
    Tool,
    parse_version,
)
from docker import DockerImage
import msys
from cinnabar.cmd.util import helper_hash


MERCURIAL_VERSION = '4.6.2'
GIT_VERSION = '2.18.0'

ALL_MERCURIAL_VERSIONS = (
    '1.9.3', '2.0.2', '2.1.2', '2.2.3', '2.3.2', '2.4.2', '2.5.4',
    '2.6.3', '2.7.2', '2.8.2', '2.9.1', '3.0.1', '3.1.2', '3.2.4',
    '3.3.3', '3.4.2', '3.5.2', '3.6.3', '3.7.3', '3.8.4', '3.9.2',
    '4.0.2', '4.1.3', '4.2.2', '4.3.3', '4.4.2', '4.5.3', '4.6.2',
)

SOME_MERCURIAL_VERSIONS = (
    '1.9.3', '2.5.4', '3.4.2',
)

assert MERCURIAL_VERSION in ALL_MERCURIAL_VERSIONS
assert all(v in ALL_MERCURIAL_VERSIONS for v in SOME_MERCURIAL_VERSIONS)


class Git(Task):
    __metaclass__ = Tool
    PREFIX = "git"

    def __init__(self, os_and_version):
        (os, version) = os_and_version.split('.', 1)
        build_image = DockerImage.by_name('build')
        if os == 'linux':
            Task.__init__(
                self,
                task_env=build_image,
                description='git v{}'.format(version),
                index='{}.git.v{}'.format(build_image.hexdigest, version),
                expireIn='26 weeks',
                command=Task.checkout(
                    'git://git.kernel.org/pub/scm/git/git.git',
                    'v{}'.format(version)
                ) + [
                    'make -C repo -j$(nproc) install prefix=/usr'
                    ' NO_GETTEXT=1 NO_OPENSSL=1 NO_TCLTK=1'
                    ' DESTDIR=/tmp/git-install',
                    'tar -C /tmp/git-install -Jcf $ARTIFACTS/git-{}.tar.xz .'
                    .format(version),
                ],
                artifact='git-{}.tar.xz'.format(version),
            )
        else:
            env = TaskEnvironment.by_name('{}.build'.format(os))
            raw_version = version
            if 'windows' not in version:
                version = {
                    version: version + '.windows.1',
                    '2.17.1': '2.17.1.windows.2',
                }.get(version)
            if version.endswith('.windows.1'):
                min_ver = version[:-len('.windows.1')]
            else:
                min_ver = version.replace('windows.', '')
            Task.__init__(
                self,
                task_env=build_image,
                description='git v{} {} {}'.format(version, env.os, env.cpu),
                index='{}.git.v{}'.format(os, raw_version),
                expireIn='26 weeks',
                command=[
                    'curl -L https://github.com/git-for-windows/git/releases/'
                    'download/v{}/MinGit-{}-{}-bit.zip'
                    ' -o git.zip'.format(version, min_ver, msys.bits(env.cpu)),
                    'unzip -d git git.zip',
                    'tar -jcf $ARTIFACTS/git-{}.tar.bz2 git'.format(
                        raw_version),
                ],
                artifact='git-{}.tar.bz2'.format(raw_version),
            )

    @classmethod
    def install(cls, name):
        url = '{{{}.artifact}}'.format(cls.by_name(name))
        if name.startswith('linux.'):
            return [
                'curl -L {} | tar -C / -Jxf -'.format(url)
            ]
        else:
            return [
                'curl -L {} -o git.tar.bz2'.format(url),
                'tar -jxf git.tar.bz2',
            ]


class Hg(Task):
    __metaclass__ = Tool
    PREFIX = "hg"

    def __init__(self, os_and_version):
        (os, version) = os_and_version.split('.', 1)
        env = TaskEnvironment.by_name('{}.build'.format(os))

        if len(version) == 40:
            # Assume it's a sha1
            pretty_version = 'r{}'.format(version)
            artifact_version = 'unknown'
            expire = '2 weeks'
        else:
            pretty_version = 'v{}'.format(version)
            artifact_version = version
            expire = '26 weeks'
        desc = 'hg {}'.format(pretty_version)
        if os == 'linux':
            artifact = 'mercurial-{}-cp27-none-linux_x86_64.whl'
        else:
            desc = '{} {} {}'.format(desc, env.os, env.cpu)
            artifact = 'mercurial-{}-cp27-cp27m-mingw.whl'

        pre_command = []
        if len(version) == 40:
            source = './hg'
            pre_command.extend(
                self.install('{}.{}'.format(os, MERCURIAL_VERSION)))
            pre_command.extend([
                'hg clone https://www.mercurial-scm.org/repo/hg -r {}'
                .format(version),
                'rm -rf hg/.hg',
            ])
        # 2.6.2 is the first version available on pypi
        elif parse_version('2.6.2') <= parse_version(version):
            source = 'mercurial=={}'
        else:
            source = 'https://mercurial-scm.org/release/mercurial-{}.tar.gz'

        Task.__init__(
            self,
            task_env=env,
            description=desc,
            index='{}.hg.{}'.format(env.hexdigest, pretty_version),
            expireIn=expire,
            command=pre_command + [
                'python -m pip wheel -v --build-option -b --build-option'
                ' $PWD/wheel -w $ARTIFACTS {}'.format(source.format(version)),
            ],
            artifact=artifact.format(artifact_version),
        )

    @classmethod
    def install(cls, name):
        hg = cls.by_name(name)
        filename = os.path.basename(hg.artifacts[0])
        return [
            'curl -L {{{}.artifact}} -o {}'.format(hg, filename),
            'python -m pip install {}'.format(filename)
        ]


def old_compatible_python():
    '''Find the oldest version of the python code that is compatible with the
    current helper'''
    from cinnabar.git import Git
    with open(os.path.join(os.path.dirname(__file__), '..', 'helper',
                           'cinnabar-helper.c')) as fh:
        min_version = None
        for l in fh:
            if l.startswith('#define MIN_CMD_VERSION'):
                min_version = l.rstrip().split()[-1][:2]
                break
        if not min_version:
            raise Exception('Cannot find MIN_CMD_VERSION')
    return list(Git.iter(
        'log', 'HEAD', '--format=%H', '-S',
        'class GitHgHelper(BaseHelper):\n    VERSION = {}'.format(min_version),
        cwd=os.path.join(os.path.dirname(__file__), '..')))[-1]


def old_helper_head():
    from cinnabar.git import Git
    from cinnabar.helper import GitHgHelper
    version = GitHgHelper.VERSION
    return list(Git.iter(
        'log', 'HEAD', '--format=%H',
        '-S', '#define CMD_VERSION {}'.format(version),
        cwd=os.path.join(os.path.dirname(__file__), '..')))[-1]


def old_helper_hash(head):
    from cinnabar.git import Git, split_ls_tree
    from cinnabar.util import one
    return split_ls_tree(one(Git.iter(
        'ls-tree', head, 'helper',
        cwd=os.path.join(os.path.dirname(__file__), '..'))))[2]


class Helper(Task):
    __metaclass__ = Tool
    PREFIX = 'helper'

    def __init__(self, os_and_variant):
        os, variant = (os_and_variant.split('.', 2) + [''])[:2]
        env = TaskEnvironment.by_name('{}.build'.format(os))

        artifact = 'git-cinnabar-helper'
        if os != 'linux':
            artifact += '.exe'
        artifacts = [artifact]

        def prefix(p, s):
            return p + s if s else s

        make_flags = []
        hash = None
        head = None
        desc_variant = variant
        extra_commands = []
        if variant == 'asan':
            make_flags.append(
                'CFLAGS="-Og -g -fsanitize=address -fno-omit-frame-pointer"')
            make_flags.append('LDFLAGS=-static-libasan')
        elif variant == 'coverage':
            make_flags.append('CFLAGS="-coverage"')
            artifacts += ['coverage.tar.xz']
            extra_commands = [
                'mv repo/git-core/{{cinnabar,connect,hg}}*.gcno repo/helper',
                '(cd repo && tar -Jcf $ARTIFACTS/coverage.tar.xz'
                ' helper/{{cinnabar,connect,hg}}*.gcno)',
            ]
        elif variant == 'old' or variant.startswith('old:'):
            if len(variant) > 3:
                head = variant[4:]
            else:
                head = old_helper_head()
            hash = old_helper_hash(head)
            variant = ''
        elif variant:
            raise Exception('Unknown variant: {}'.format(variant))

        if os == 'linux':
            make_flags.append('CURL_COMPAT=1')
        else:
            make_flags.append('USE_LIBPCRE1=YesPlease')
            make_flags.append('USE_LIBPCRE2=')
            make_flags.append('CFLAGS+=-DCURLOPT_PROXY_CAINFO=246')

        hash = hash or helper_hash()

        Task.__init__(
            self,
            task_env=env,
            description='helper {} {}{}'.format(
                env.os, env.cpu, prefix(' ', desc_variant)),
            index='helper.{}.{}.{}{}'.format(
                hash, env.os, env.cpu, prefix('.', variant)),
            expireIn='26 weeks',
            command=Task.checkout(commit=head) + [
                'make -C repo helper -j $(nproc) prefix=/usr{}'.format(
                    prefix(' ', ' '.join(make_flags))),
                'mv repo/{} $ARTIFACTS/'.format(artifact),
            ] + extra_commands,
            artifacts=artifacts,
        )

    @classmethod
    def install(cls, name):
        helper = cls.by_name(name)
        filename = os.path.basename(helper.artifacts[0])
        return [
            'curl --compressed -o {} -L {{{}.artifacts[0]}}'.format(
                filename, helper),
            'chmod +x {}'.format(filename),
            'git config --global cinnabar.helper $PWD/{}'.format(filename),
        ]