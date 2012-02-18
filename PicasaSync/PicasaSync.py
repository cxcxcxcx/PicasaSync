#! /usr/bin/env python

import sys
if sys.hexversion < 0x020700F0:
	raise SystemExit('This scripts needs at least Python 2.7')

import logging, os, mimetypes, calendar, argparse

try:
	import googlecl
except ImportError:
	raise SystemExit('Error importing the googlecl module. In debian/ubuntu you can install it by doing "sudo apt-get install googlecl"')
import googlecl.authentication
import googlecl.config
import googlecl.picasa as picasa
import googlecl.picasa.service as picasa_service

try:
	import iso8601
except ImportError:
	raise SystemExit('Error importing the iso8601 module. In debian/ubuntu you can install it by doing "sudo apt-get install python-iso8601"')

LOG = logging.getLogger("PicasaSync")

supported_types = set(['image/jpeg', 'image/tiff', 'image/x-ms-bmp', 'image/gif', 'image/x-photoshop', 'image/png'])

def get_disk_albums(path, max_photos):
	albums = {}
	for root, dirs, files in os.walk(path):
		supported_files = sorted([f for f in files if mimetypes.guess_type(f)[0] in supported_types])
		if root == path or len(supported_files) == 0:
			continue
		supported_files = [(googlecl.safe_decode(f), os.path.join(root, f), os.stat(os.path.join(root,f)).st_mtime) for f in supported_files]
		album = googlecl.safe_decode(os.path.relpath(root, path))
		if len(supported_files) < max_photos:
			albums[(album, album)] = supported_files
		else:
			for i in xrange(0, (len(supported_files) + max_photos - 1) / max_photos):
				LOG.debug('Splicing album "%s (%s)" with photos from "%s" to "%s"' % (album, i + 1, supported_files[i * max_photos][0], supported_files[min(i * max_photos + max_photos - 1, len(supported_files) - 1)][0]))
				albums[(album + ' (%s)' % (i + 1), album)] = supported_files[i * max_photos:i * max_photos + max_photos]
	return albums

def get_picasa_client(config, debug = False):
	client = picasa_service.SERVICE_CLASS(config)
	client.debug = debug
	client.email = config.lazy_get(picasa.SECTION_HEADER, 'user')
	auth_manager = googlecl.authentication.AuthenticationManager('picasa', client)
	set_token = auth_manager.set_access_token()
	if not set_token:
		LOG.error("Error using OAuth token. You have to authenticate with googlecl.")
		return None
	return client

def upload_photo(client, album, photo):
	client.insert_media_list(album, [googlecl.safe_decode(photo)])

def sync(args):
	config = googlecl.config.load_configuration()
	picasa_client = get_picasa_client(config, args.debug)
	if not picasa_client:
		return

	albums = get_disk_albums(args.path, args.max_photos)
	if len(albums) == 0:
		return
	
	picasa_albums = picasa_client.build_entry_list(titles = [None], force_photos = False)
	picasa_albums = dict([(googlecl.safe_decode(a.title.text), a) for a in picasa_albums])
	for album, photos in albums.iteritems():
		album_path = album[1]
		album = album[0]
		if not album in picasa_albums:
			LOG.info('Uploading album "%s" not found in Picasa' % album)
			if not args.dry_run:
				new_album = picasa_client.CreateAlbum(title = album, summary = None, access = config.lazy_get(picasa.SECTION_HEADER, 'access'), date = None)
				for photo, f, ts in photos:
					upload_photo(picasa_client, new_album, f)
		else:
			LOG.debug('Checking album "%s"...' % album)
			picasa_photos = picasa_client.GetEntries('/data/feed/api/user/default/albumid/%s?kind=photo' % picasa_albums[album].gphoto_id.text)
			picasa_photos = dict([(googlecl.safe_decode(p.title.text), p) for p in picasa_photos])
			for photo, f, ts in photos:
				if not photo in picasa_photos:
					LOG.info('Uploading "%s" because it is not in the album "%s"' % (photo, album))
					if not args.dry_run:
						upload_photo(picasa_client, picasa_albums[album], f)
				elif ts > calendar.timegm(iso8601.parse_date(picasa_photos[photo].updated.text).timetuple()):
					LOG.info('Uploading "%s" because it is newer than the one in the album "%s"' % (photo, album))
					if not args.dry_run:
						picasa_client.Delete(picasa_photos[photo])
						upload_photo(picasa_client, picasa_albums[album], f)

def run():
	parser = argparse.ArgumentParser(description = 'Sync a directory with your Picasa Web account')
	parser.add_argument('-n', '--dry-run', dest = 'dry_run', action = 'store_true', help = 'Do everything except creating albums and photos')
	parser.add_argument('-d', '--debug', dest = 'debug', action = 'store_true', help = 'Debug Picasa API usage')
	parser.add_argument('-v', '--verbose', dest = 'verbose', action = 'count', help = 'Verbose output (can be given more than once)')
	parser.add_argument('-m', '--max-photos', metavar = 'NUMBER', dest = 'max_photos', type = int, default = 1000, help = 'Maximum number of photos in album (limited to 1000)')
	parser.add_argument('path', metavar = 'PATH', help = 'Parent directory of the albums to sync')
	args = parser.parse_args()

	if args.verbose == 1:
		log_level = logging.INFO
	elif args.verbose >= 2:
		log_level = logging.DEBUG
	else:
		log_level = logging.WARNING

	logging.basicConfig(level = log_level)

	if args.max_photos > 1000:
		LOG.warn('Maximum number of photos in album is bigger than the Picasa limit (1000), using 1000 as limit')
		args.max_photos = 1000

	sync(args)

def main():
	try:
		run()
	except KeyboardInterrupt:
		pass

if __name__ == '__main__':
		main()

