from setuptools import setup, find_packages
from io import open

setup(
    name='TSB_AD',  # Replace with your own package name
    version='1.5',  # The version of your package
    author='The Datum Lab',  # Your name
    description='Time-Series Anomaly Detection Benchmark',  # A short description
    long_description=open('README.md', encoding='utf-8').read(),  # Long description read from the README.md
    long_description_content_type='text/markdown',  # Type of the long description, typically text/markdown or text/x-rst
    url='https://github.com/TheDatumOrg/TSB-AD',  # Link to the repository or website
    packages=find_packages(),  # List of all Python import packages that should be included in the Distribution Package
    classifiers=[
        # Trove classifiers
        # Full list: https://pypi.org/classifiers/
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
    install_requires=[
        'tqdm',
        'torchinfo',
        'h5py',
        'einops',
        'numpy>=1.24.3,<2.0',
        'matplotlib>=3.7.5',
        'pandas>=2.0.3',
        'arch>=5.3.1',
        'hurst>=0.0.5',
        'tslearn>=0.6.3',
        'cython>=3.0.10',
        'scikit-learn>=1.3.2',
        'stumpy>=1.12.0',
        'networkx>=3.1',
        'transformers>=4.38.0',
        'torch>=1.8.0',
    ],
    package_data={'TSB_AD.quality.experiments': ['lists/*.csv'], 'TSB_AD.quality.experiments.database': ['schema.sql', 'docker-compose.yml']},
    extras_require={
        # Pollution of time series (TSB_AD.quality). JENGA and Icewafl run in a private Python 3.10
        # environment with its own Java, built by `uv` on first use (see TSB_AD/quality/runtime.py).
        'quality': ['uv'],
        # Experiments that store their results in Postgres (TSB_AD.quality.experiments).
        'quality-experiments': ['uv', 'psycopg2-binary', 'minio>=7.2.20', 'pypots>=1.5'],
    },
    python_requires='>=3.8',  # Minimum version requirement of the package
    entry_points={},
    license="Apache-2.0 license",
    include_package_data=True,  # Whether to include non-code files in the package
    zip_safe=False,  # Whether the package can be run out of a zip file
)