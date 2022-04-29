from setuptools import setup

setup(
    name='sftools',
    version='1.0.6',
    packages=[
        'sftools',
        'sftools/custom',
    ],
    install_requires=[
        'simple-salesforce',
        'ipython',
        'requests',
    ],
    scripts=[
        'scripts/sf-case',
        'scripts/sf-object',
        'scripts/sf-shell',
        'scripts/sf-timecard',
        'scripts/sf-user',
    ],
)
