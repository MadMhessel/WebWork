python -m pip install -U pip setuptools wheel build
python -m pip install -U --only-binary=:all: --upgrade-strategy eager
python -m pip install --only-binary=:all: tgcrypto==1.2.5
