from pip._internal.req import parse_requirements
import setuptools

install_requirements = parse_requirements('requirements.txt', session='install')

requirements = [ir.requirement for ir in install_requirements]

setuptools.setup(install_requires=requirements)
