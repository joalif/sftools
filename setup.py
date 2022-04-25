from setuptools import setup

setup(
    name='sftools',
    version='1.0.6',
    packages=['sftools'],
    install_requires=[
        'simple-salesforce',
        'ipython',
        'requests',
    ],
    scripts=[
        'scripts/sf-shell',
        'scripts/sf-case',
    ],
)
