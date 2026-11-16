"""Telegram collection regression checks with a fake client; no login/network."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telethon.tl.types import InputMessagesFilterPhotos, InputPeerEmpty, PeerChannel
from aimw.collection import telegram_search as search


def message(number):
    return SimpleNamespace(id=number, peer_id=PeerChannel(7), message='crypto investment', photo=object(), video=None, document=None)


class TelegramPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_filter_pages_past_known_posts_without_redownloading(self):
        pages = [
            SimpleNamespace(messages=[message(1)], chats=[SimpleNamespace(id=7, username='channel')], next_rate=1),
            SimpleNamespace(messages=[message(2)], chats=[SimpleNamespace(id=7, username='channel')], next_rate=2),
        ]
        client = AsyncMock()
        client.is_user_authorized.return_value = True
        client.side_effect = pages
        client.get_input_entity.return_value = InputPeerEmpty()
        save = AsyncMock(return_value={'video_id': 'fresh', 'url': 'https://t.me/channel/2'})
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(search, '_build_client', return_value=client), patch.object(search, 'should_collect_text', return_value=True), patch.object(search, '_save_photo', save):
                results = await search.search_and_collect('crypto', api_id=1, api_hash='test', session_str='test', media_dir=Path(folder), limit=1, content_types=['photo'], exclude_urls={'https://t.me/channel/1'})
        self.assertEqual([item['video_id'] for item in results], ['fresh'])
        self.assertEqual(client.await_count, 2)
        self.assertIsInstance(client.await_args_list[0].args[0].filter, InputMessagesFilterPhotos)
        save.assert_awaited_once()
        self.assertEqual(save.await_args.args[2], 'https://t.me/channel/2')
        client.disconnect.assert_awaited_once()

    async def test_repeated_page_exits_without_duplicate_downloads(self):
        page = SimpleNamespace(messages=[message(1)], chats=[SimpleNamespace(id=7, username='channel')], next_rate=1)
        client = AsyncMock(return_value=page)
        client.is_user_authorized.return_value = True
        client.get_input_entity.return_value = InputPeerEmpty()
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(search, '_build_client', return_value=client), patch.object(search, '_save_photo', new_callable=AsyncMock) as save:
                results = await search.search_and_collect('crypto', api_id=1, api_hash='test', session_str='test', media_dir=Path(folder), content_types=['photo'], exclude_urls={'https://t.me/channel/1'})
        self.assertEqual(results, [])
        self.assertLessEqual(client.await_count, 3)
        save.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
