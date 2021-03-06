#!/usr/bin/env python

# Copyright: (c) 2020, Felix Fontein <felix@fontein.de>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import argparse
import json
import os
import random
import subprocess
import sys


COLORS = {
    'emph': 1,
    'gray': 37,
    'black': 30,
    'white': 97,
    'green': 32,
    'red': 31,
    'yellow': 33,
}


def colorize(text, color, use_color=True):
    if not use_color:
        return text
    color_id = COLORS.get(color)
    if color_id is None:
        return text
    return '\x1b[{0}m{1}\x1b[0m'.format(color_id, text)


def run(command, catch_output=False, use_color=True):
    sys.stdout.write(colorize('[RUN] {0}\n'.format(' '.join(command)), 'emph', use_color))
    sys.stdout.flush()
    if not catch_output:
        return subprocess.call(command), None, None
    process_result = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process_result.communicate()
    return process_result.returncode, stdout, stderr


def get_common_parent(*directories):
    parent = directories[0]
    for directory in directories[1:]:
        while os.path.relpath(directory, parent).startswith('..'):
            old_parent, parent = parent, os.path.dirname(parent)
            if old_parent == parent:
                break
    return parent


def get_default_container(use_color=True):
    try:
        try:
            from ansible_test._internal.util_common import docker_qualify_image
        except ImportError:
            from ansible_test._internal.util import docker_qualify_image

        image = docker_qualify_image('default')
        if image:
            return image

        print(colorize('WARNING: cannot load default docker container version from ansible-test: default image not known', 'red', use_color))
    except Exception as exc:
        print(colorize('WARNING: cannot load default docker container version from ansible-test: {0}'.format(exc), 'red', use_color))
    return 'quay.io/ansible/default-test-container:1.14'


def pull_docker_image(image_name, use_color=True):
    for tries in range(3):
        rc, dummy, dummy = run(['docker', 'pull', image_name], use_color=use_color)
        if rc == 0:
            return
        print(colorize('WARNING: pulling docker image failed, retrying...', 'red', use_color))
    print(colorize('FATAL ERROR while pulling docker image', 'red', use_color))
    sys.exit(-1)


def main():
    parser = argparse.ArgumentParser(description='Extra sanity test runner.')
    parser.add_argument('--color',
                        action='store_true',
                        help='use ANSI colors')
    parser.add_argument('--docker-no-pull',
                        action='store_true',
                        help='do not try to pull the docker image')
    parser.add_argument('targets',
                        metavar='TARGET',
                        nargs='*',
                        help='targets')

    args = parser.parse_args()

    use_color = sys.stdout.isatty()
    if args.color:
        use_color = True

    cwd = os.getcwd()
    root = cwd
    my_dir = '.'
    try:
        my_dir = os.path.dirname(__file__)
        root = get_common_parent(root, my_dir)
    except Exception:  # pylint: disable=broad-except
        pass

    targets = list(args.targets)

    container_name = 'ansible-test-{0}'.format(random.getrandbits(64))
    output_filename = 'output-{0}.json'.format(random.getrandbits(32))

    image_name = get_default_container(use_color=use_color)
    if not args.docker_no_pull:
        pull_docker_image(image_name, use_color=use_color)

    result = None
    run([
        'docker', 'run', '--detach',
        '--workdir', os.path.abspath(cwd),
        '--name', container_name,
        image_name,
        '/bin/sh', '-c', 'sleep 50m',
    ], use_color=use_color)
    try:
        run(['docker', 'cp', root, '{0}:{1}'.format(container_name, os.path.dirname(root))], use_color=use_color)
        # run(['docker', 'exec', container_name, '/bin/sh', '-c', 'ls -lah ; pwd'])
        command = ['docker', 'exec', container_name]
        command.extend(['python3.7', os.path.relpath(os.path.join(my_dir, 'runner.py'), cwd)])
        command.extend(['--cleanup', '--install-requirements', '--output', output_filename])
        if use_color:
            command.extend(['--color'])
        command.extend(targets)
        run(command, use_color=use_color)
        dummy, result, stderr = run(['docker', 'exec', container_name, 'cat', output_filename], catch_output=True, use_color=use_color)
        if stderr:
            print(colorize('WARNING: {0}'.format(stderr.decode('utf-8').strip()), 'emph', use_color))
    except Exception as exc:  # pylint: disable=broad-except
        print(colorize('FATAL ERROR during execution: {0}'.format(exc), 'emph', use_color))
    finally:
        try:
            run(['docker', 'rm', '-f', container_name], use_color=use_color)
        except Exception as exc:  # pylint: disable=broad-except
            print(colorize('ERROR while removing docker container: {0}'.format(exc), 'emph', use_color))
    if result is None:
        sys.exit(-1)

    try:
        result = json.loads(result.decode('utf-8'))
    except Exception as exc:  # pylint: disable=broad-except
        print(colorize('FATAL ERROR while receiving output: {0}'.format(exc), 'red', use_color))
        sys.exit(-1)

    failed_tests = []
    total_errors = 0
    for test, data in result.items():
        if data.get('skipped'):
            continue
        if not data['success']:
            failed_tests.append(test)
            if 'errors' in data:
                total_errors += len(data['errors'])
    if total_errors or failed_tests:
        print(colorize('Total of {0} errors in the following {1} tests (out of {2}):'.format(total_errors, len(failed_tests), len(result)), 'emph', use_color))
        for test in sorted(failed_tests):
            print(colorize(test, 'red', use_color))
        sys.exit(-1)
    else:
        print(colorize('Success.', 'green', use_color))
        sys.exit(0)


if __name__ == '__main__':
    main()
