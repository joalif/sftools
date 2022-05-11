
import argparse
import time

from copy import copy
from functools import partial
from types import SimpleNamespace

from sftools.sf import SF
from sftools.config import SFConfig


class SFArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, action_required=False, **kwargs):
        super().__init__(*args, **kwargs)

        self.add_argument('--dry-run', action='store_true',
                          help='Dry-run only, do not make any changes')
        self.add_argument('-v', '--verbose', action='store_true',
                          help='Be verbose.')

        config = self.add_mutually_exclusive_group()
        config.add_argument('--config',
                            help='Alternate config file to use')
        config.add_argument('-P', '--production', action='store_true',
                            help='Use standard production server config file (default)')
        config.add_argument('-S', '--sandbox', action='store_true',
                            help='Use sandbox server config file')
        self.config_group = config

        action = self.add_mutually_exclusive_group(required=action_required)
        action.add_argument('--show-full-config', action='store_true',
                            help='Show current full config (including defaults)')
        action.add_argument('--show-config', action='store_true',
                            help='Show current user config (without defaults)')
        self.action_group = action

    def _parse_args(self, *args, **kwargs):
        opts = super().parse_args(*args, **kwargs)
        opts.functions = SimpleNamespace()
        opts.functions.SF = partial(self.sf, opts)
        return opts

    def parse_args(self, *args, **kwargs):
        opts = self._parse_args(*args, **kwargs)
        if opts.verbose:
            opts_copy = copy(opts)
            del opts_copy.functions
            print(opts_copy)
        return opts

    def sf(self, opts, *args, **kwargs):
        kwargs.setdefault('verbose', opts.verbose)

        config = None
        if opts.config:
            config = SFConfig(opts.config)
        elif opts.production:
            config = SFConfig.PRODUCTION()
        elif opts.sandbox:
            config = SFConfig.SANDBOX()

        sf = SF(config, *args, **kwargs)

        if opts.show_config:
            sf.config.show()
        elif opts.show_full_config:
            sf.config.show(full=True)

        return sf


class SFObjectArgumentParser(SFArgumentParser):
    def __init__(self, *args, default_fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_fields = default_fields

        label = self.add_mutually_exclusive_group()
        label.add_argument('--label', action='store_true',
                           default=None,
                           help='Print field name (default if more than 1 field)')
        label.add_argument('--no-label', action='store_false',
                           dest='label',
                           help='Do not print field name (default if only 1 field)')

        field_help = 'Field(s) to display'
        if default_fields:
            field_help += f' (default {",".join(default_fields)})'
        else:
            field_help += ' (default all fields)'
        field_group = self.add_mutually_exclusive_group()
        field_group.add_argument('-f', '--field', action='append',
                                 help=field_help)
        field_group.add_argument('--all-fields', action='store_true',
                                 help='Display all fields')

        self.add_argument('--limit', type=int, default=0,
                          help='Limit number of matched objects')

    def _parse_args(self, *args, **kwargs):
        opts = super()._parse_args(*args, **kwargs)

        if opts.all_fields:
            opts.field = []
        elif not opts.field and self.default_fields:
            opts.field = self.default_fields

        opts.functions.delete = partial(self.delete, opts)
        opts.functions.dumpfields = partial(self.dumpfields, opts)
        opts.query_kwargs = {
            'LIMIT': opts.limit,
            'SELECT': opts.field,
        }

        return opts

    def sf(self, opts, *args, **kwargs):
        kwargs.setdefault('preload_fields', not opts.field)
        kwargs.setdefault('verbose', opts.verbose)
        kwargs.setdefault('dry_run', opts.dry_run)
        return super().sf(opts, *args, **kwargs)

    def limit_objects(self, opts, objects):
        if opts.limit:
            return objects[:opts.limit]
        return objects

    def delete(self, opts, objects):
        objects = self.limit_objects(opts, objects)
        for o in objects:
            print(f'DELETING object Id {o.Id}')
            time.sleep(1)
            o.delete()

    def dumpfields(self, opts, objects):
        objects = self.limit_objects(opts, objects)
        for o in objects:
            o.dumpfields(fields=opts.field, label=opts.label)
