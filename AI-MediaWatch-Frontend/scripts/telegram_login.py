"""Authorize the Telegram collector with a login code or --qr.

Run from the project folder. API credentials come from my.telegram.org/apps.
For QR login install qrcode, then run this script with --qr. QR codes and the
printed session are credentials: keep them private. No remote QR service is used.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
from pathlib import Path


def _save_settings(env_path: Path, api_id: int, api_hash: str, session: str) -> None:
    from dotenv import set_key

    for key, value in {
        'AIMW_TELEGRAM_API_ID': str(api_id),
        'AIMW_TELEGRAM_API_HASH': api_hash,
        'AIMW_TELEGRAM_SESSION': session,
    }.items():
        set_key(str(env_path), key, value, quote_mode='always')


async def _qr_sign_in(client) -> None:
    try:
        import qrcode
    except ImportError:
        raise SystemExit(
            'QR support is missing. Run:\n'
            '.\\.bootstrap\\Scripts\\uv.exe pip install --python '
            '.\\.venv\\Scripts\\python.exe qrcode'
        ) from None
    from telethon.errors import SessionPasswordNeededError

    print('\nOpen Telegram on your phone: Settings > Devices > Link Desktop Device.')
    print('Scan the QR below using Telegram, not the ordinary camera app.')
    print('Keep this QR private. It authorizes access to your account.\n')
    for attempt in range(3):
        login = await client.qr_login()
        qr = qrcode.QRCode(border=4)
        qr.add_data(login.url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        try:
            await login.wait()
            return
        except asyncio.TimeoutError:
            if attempt < 2:
                print('\nQR expired. Scan the NEW QR below.\n')
        except SessionPasswordNeededError:
            await client.sign_in(password=getpass.getpass('Telegram two-step verification password: '))
            return
    raise SystemExit('QR login timed out. Run the command again when your phone is ready.')


async def _main(use_qr: bool = False, save_env: bool = False) -> None:
    env_path = Path(__file__).resolve().parents[1] / '.env'
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        pass
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.errors import FloodWaitError, RPCError
    except ImportError:
        raise SystemExit('telethon is not installed; run uv sync first') from None

    api_id_raw = os.environ.get('AIMW_TELEGRAM_API_ID') or input('api_id: ').strip()
    api_hash = os.environ.get('AIMW_TELEGRAM_API_HASH') or getpass.getpass('api_hash (hidden while typing): ').strip()
    try:
        api_id = int(api_id_raw)
    except ValueError:
        raise SystemExit('api_id must be a number') from None

    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.connect()
        if use_qr:
            await _qr_sign_in(client)
        else:
            print('\nUse the NEW code for this script, not an old website login code.')
            print('If no code arrives, press Ctrl+C and run again with --qr.\n')
            await client.start()
        me = await client.get_me()
        print('\n' + '=' * 64)
        print(f'Logged in as: {me.first_name} (@{me.username})')
        if save_env:
            _save_settings(env_path, api_id, api_hash, client.session.save())
            print('Telegram credentials saved directly to the project .env.')
            print('The session has not been printed. Restart the AIMW backend.')
        else:
            print('Save the following settings in .env. Keep them private.\n')
            print(f'AIMW_TELEGRAM_API_ID={api_id}')
            print(f'AIMW_TELEGRAM_API_HASH={api_hash}')
            print(f'AIMW_TELEGRAM_SESSION={client.session.save()}')
            print('\nReplace existing entries, then restart the AIMW backend.')
        print('=' * 64)
    except FloodWaitError as exc:
        raise SystemExit(f'Telegram requested a wait of {exc.seconds} seconds. Wait before trying again.') from None
    except RPCError as exc:
        raise SystemExit(f'Telegram rejected the login ({type(exc).__name__}). Check your credentials and account status.') from None
    finally:
        await client.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Connect the Telegram collector to your account.')
    parser.add_argument('--qr', action='store_true', help='Approve login by scanning a local QR code in Telegram.')
    parser.add_argument('--save-env', action='store_true', help='Save credentials directly to the project .env without printing them.')
    args = parser.parse_args()
    try:
        asyncio.run(_main(use_qr=args.qr, save_env=args.save_env))
    except KeyboardInterrupt:
        print('\nLogin cancelled.')
