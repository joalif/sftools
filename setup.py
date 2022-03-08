from setuptools import setup

setup(
    name='sftools',
    version='1.0.4',
    packages=['sftools'],
    install_requires=[
        'simple-salesforce',
        'ipython',
        'requests',
    ],
    scripts=['sf-shell'],
)
