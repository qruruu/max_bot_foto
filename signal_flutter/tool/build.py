"""Build one versioned, self-contained Flutter web bundle for Signal."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--flutter', default='flutter')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = str(uuid4())
    subprocess.run([args.flutter, 'build', 'web', '--release', '--csp',
                    '--no-web-resources-cdn', '--pwa-strategy=none',
                    f'--dart-define=APP_VERSION={version}'], cwd=root, check=True)
    output = root / 'build/web'
    shutil.copyfile(output / 'index.html', output / 'citizens.html')
    (output / 'version.json').write_text(json.dumps({'version': version}))


if __name__ == '__main__':
    main()
