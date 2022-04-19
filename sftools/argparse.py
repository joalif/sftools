
import argparse

from sftools.sf import SF
from sftools.config import SFConfig


class SFArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, action_required=True, **kwargs):
        super().__init__(*args, **kwargs)

        self.add_argument('-v', '--verbose', action='store_true',
                          help='Be verbose.')

        config = self.add_mutually_exclusive_group()
        config.add_argument('-c', '--config',
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
