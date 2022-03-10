from setuptools import setup

setup(
    name='sftools',
    version='1.0.5',
    packages=['sftools'],
    install_requires=[
        'simple-salesforce',
        'ipython',
        'requests',
    ],
    scripts=['sf-shell'],
)
