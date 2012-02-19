#! /usr/bin/env python

import sys
if sys.hexversion < 0x020700F0:
	raise SystemExit('This scripts needs at least Python 2.7')

import logging, os, mimetypes, argparse, urllib

try:
	import googlecl
except ImportError:
	raise SystemExit('Error importing the googlecl module. In debian/ubuntu you can install it by doing "sudo apt-get install googlecl"')
import googlecl.authentication
import googlecl.config
import googlecl.picasa as picasa
import googlecl.picasa.service as picasa_service

import atom
import gdata.photos

MAX_PHOTOS_PER_ALBUM = 1000

LOG = logging.getLogger("PicasaSync")

supported_types = set(['image/jpeg', 'image/tiff', 'image/x-ms-bmp', 'image/gif', 'image/x-photoshop', 'image/png'])

def _entry_ts(entry):
	return int(long(entry.timestamp.text) / 1000)

def get_disk_albums(path, max_photos = None):
	"""Returns a dictionary with all the local albums in the given path

	Args:
		path: directory containing all the local albums
		max_photos: if not None, splice all albums with more than max_photos photos in several albums

	Returns:
		A dictionary of the form:
		{ (u'Album title', 'album_dir', last_modification_timestamp): [(u'Photo title', 'photo_path', last_modification_timestamp), ...] }
	"""
	albums = {}
	for root, dirs, files in os.walk(path):
		supported_files = sorted([f for f in files if mimetypes.guess_type(f)[0] in supported_types])
		if root == path or len(supported_files) == 0:
			continue
		supported_files = [(googlecl.safe_decode(f), os.path.join(root, f), int(os.stat(os.path.join(root,f)).st_mtime)) for f in supported_files]
		album = googlecl.safe_decode(os.path.relpath(root, path))
		if not max_photos or (len(supported_files) < max_photos):
			albums[(album, album, int(os.stat(root).st_mtime))] = supported_files
		else:
			for i in xrange(0, (len(supported_files) + max_photos - 1) / max_photos):
				LOG.debug('Splicing album "%s (%s)" with photos from "%s" to "%s"' % (album, i + 1, supported_files[i * max_photos][0], supported_files[min(i * max_photos + max_photos - 1, len(supported_files) - 1)][0]))
				albums[(album + ' (%s)' % (i + 1), album, int(os.stat(root).st_mtime))] = supported_files[i * max_photos:i * max_photos + max_photos]
	return albums

def get_picasa_albums(client):
	"""Returns a dictionary with all the albums in your Picasa account.

	Args:
		client: a googlecl.picasa.service.PhotosServiceCL object

	Returns:
		A dictionary of the form:
		{ u'Album title': gdata.photos.AlbumEntry }
	"""
	picasa_albums = client.build_entry_list(titles = [None], force_photos = False)
	return dict([(googlecl.safe_decode(a.title.text), a) for a in picasa_albums])

def get_picasa_photos(client, album):
	"""Returns a dictionary with all the photos in a given album.

	Args:
		client: a googlecl.picasa.service.PhotosServiceCL object
		album: a gdata.photos.AlbumEntry of the album

	Returns:
		A dictionary of the form:
		{ u'Photo title': gdata.photos.PhotoEntry }
	"""
	picasa_photos = client.GetEntries('/data/feed/api/user/default/albumid/%s?kind=photo' % album.gphoto_id.text)
	return dict([(googlecl.safe_decode(p.title.text), p) for p in picasa_photos])

def get_picasa_client(options = None):
	config = googlecl.config.load_configuration()
	client = picasa_service.SERVICE_CLASS(config)
	client.debug = False if not options else options.debug
	client.email = config.lazy_get(picasa.SECTION_HEADER, 'user')
	auth_manager = googlecl.authentication.AuthenticationManager('picasa', client)
	set_token = auth_manager.set_access_token()
	if not set_token:
		LOG.error('Error using OAuth token. You have to authenticate with googlecl using "google picasa list-albums --force-auth" and following the instructions')
		return None
	return client

def upload_photo(client, album, photo_title, filename, timestamp, options = None, reason = None):
	if (options and options.dry_run) or LOG.isEnabledFor(logging.INFO):
		msg = 'Uploading file "%s"%s' % (filename, reason if reason else '')
		if options and options.dry_run:
			LOG.warn('[DRYRUN] %s' % msg)
		else:
			LOG.info(msg)

	if not options or not options.dry_run:
		metadata = gdata.photos.PhotoEntry()
		metadata.title = atom.Title(text = photo_title)
		metadata.timestamp = gdata.photos.Timestamp(text = str(long(timestamp) * 1000))
		client.InsertPhoto(album, metadata, filename, mimetypes.guess_type(filename)[0])

def download_photo(album_path, photo, options = None, reason = None):
	filename = os.path.join(album_path, photo.title.text)

	if (options and options.dry_run) or LOG.isEnabledFor(logging.INFO):
		msg = 'Downloading file "%s"%s' % (filename, reason if reason else '')
		if options and options.dry_run:
			LOG.warn('[DRYRUN] %s' % msg)
		else:
			LOG.info(msg)

	if not options or not options.dry_run:
		tmpfilename = filename + '.part'
		urllib.urlretrieve(photo.content.src, tmpfilename)
		timestamp = _entry_ts(photo)
		os.utime(tmpfilename, (timestamp, timestamp))
		os.rename(tmpfilename, filename)

def delete_photo(client, photo, options = None, reason = None):
	if reason and ((options and options.dry_run) or LOG.isEnabledFor(logging.INFO)):
		msg = 'Deleting remote photo "%s"%s' % (photo.title.text, reason)
		if options and options.dry_run:
			LOG.warn('[DRYRUN] %s' % msg)
		else:
			LOG.info(msg)

	if not options or not options.dry_run:
		client.Delete(photo)

def replace_photo(client, album, photo, filename, timestamp, options = None, reason = None):
	delete_photo(client, photo, options)
	upload_photo(client, album, photo.title.text, filename, timestamp, options, reason)

def create_album(client, title, timestamp = None, options = None, reason = None):
	if (options and options.dry_run) or LOG.isEnabledFor(logging.INFO):
		msg = 'Uploading album "%s"%s' % (title, reason if reason else '')
		if options and options.dry_run:
			LOG.warn('[DRYRUN] %s' % msg)
		else:
			LOG.info(msg)

	if not options or not options.dry_run:
		access = googlecl.picasa._map_access_string(client.config.lazy_get(picasa.SECTION_HEADER, 'access'))
		return client.InsertAlbum(title = title, summary = None, access = access, timestamp = str(timestamp * 1000))
	else:
		return None

def delete_album(client, album, options = None, reason = None):
	if (options and options.dry_run) or LOG.isEnabledFor(logging.INFO):
		msg = 'Deleting album "%s"%s' % (album.title.text, reason if reason else '')
		if options and options.dry_run:
			LOG.warn('[DRYRUN] %s' % msg)
		else:
			LOG.info(msg)

	if not options or not options.dry_run:
		client.Delete(album)

def create_dir(root, title, timestamp, options = None, reason = None):
	path = os.path.join(root, title)

	if (options and options.dry_run) or LOG.isEnabledFor(logging.INFO):
		msg = 'Creating directory "%s"%s' % (path, reason if reason else '')
		if options and options.dry_run:
			LOG.warn('[DRYRUN] %s' % msg)
		else:
			LOG.info(msg)

	if not options or not options.dry_run:
		try:
			if not os.path.isdir(path):
				os.makedirs(path)
			os.utime(path, (timestamp, timestamp))
		except Exception as e:
			LOG.warn('Cannot create local directory: ' + str(e))
			return None

	return path

def delete_dir(root, title, options = None, reason = None):
	path = os.path.join(root, title)

	if (options and options.dry_run) or LOG.isEnabledFor(logging.INFO):
		msg = 'Deleting directory "%s"%s' % (path, reason if reason else '')
		if options and options.dry_run:
			LOG.warn('[DRYRUN] %s' % msg)
		else:
			LOG.info(msg)

	if not options or not options.dry_run:
		try:
			os.rmdir(path)
		except Exception as e:
			LOG.warn('Cannot delete local directory: ' + str(e))

def delete_file(filename, options = None, reason = None):
	if (options and options.dry_run) or LOG.isEnabledFor(logging.INFO):
		msg = 'Deleting file "%s"%s' % (filename, reason if reason else '')
		if options and options.dry_run:
			LOG.warn('[DRYRUN] %s' % msg)
		else:
			LOG.info(msg)

	if not options or not options.dry_run:
		try:
			os.remove(filename)
		except Exception as e:
			LOG.warn('Cannot delete local file: ' + str(e))

def sync(options, root):
	client = get_picasa_client(options)
	if not client:
		return

	disk_albums = get_disk_albums(root, options.max_photos)
	picasa_albums = get_picasa_albums(client)
	
	for (album_title, album_dir, album_ts), photos in disk_albums.iteritems():
		# Local albums not in remote
		if not album_title in picasa_albums:
			if options.upload:
				new_album = create_album(client, album_title, album_ts, options, ' because it does not exist in Picasa')
				for photo_title, filename, timestamp in photos:
					upload_photo(client, new_album, photo_title, filename, timestamp, options)
			if options.download and options.delete_albums:
				for photo_title, filename, timestamp in photos:
					delete_file(filename, options)
				delete_dir(root, album_dir, options, ' because it does not exist in Picasa')
		# Common albums
		else:
			LOG.debug('Checking album "%s"...' % album_title)
			picasa_photos = get_picasa_photos(client, picasa_albums[album_title])
			for photo_title, filename, timestamp in photos:
				# Local photo not in remote
				if not photo_title in picasa_photos:
					if options.upload:
						upload_photo(client, picasa_albums[album_title], photo_title, filename, timestamp, options, ' because it is not in the album "%s"' % album_title)
					if options.download and options.delete_photos:
						delete_file(filename, options, ' because it is not in the album "%s"' % album_title)
				# Common photo
				elif options.update:
					if options.upload and (timestamp > _entry_ts(picasa_photos[photo_title]) or options.force_update):
						replace_photo(client, picasa_albums[album_title], picasa_photos[photo_title], filename, timestamp, options, ' %sbecause it is newer than the one in the album "%s"' % ('[FORCED] ' if options.force_update else '', album_title))
					if options.download and (timestamp < _entry_ts(picasa_photos[photo_title]) or options.force_update):
						download_photo(os.path.join(root, album_dir), picasa_photos[photo_title], options, ' %sbecause it is newer than the one in the album "%s"' % ('[FORCED] ' if options.force_update else '', album_title))

			# Remote photos not in local
			for photo_title, photo in ((t, p) for (t, p) in picasa_photos.iteritems() if t not in (p[0] for p in photos)):
				if options.upload and options.delete_photos:
					delete_photo(client, photo, options, ' because it does not exist in the local album')
				if options.download:
					download_photo(os.path.join(root, album_dir), photo, options, ' because it does not exist in the local album')

	# Remote albums not in local
	for album_title, album in ((t, a) for (t, a) in picasa_albums.iteritems() if t not in (a[0] for a in disk_albums)):
		if options.upload and options.delete_albums:
			delete_album(client, album, options, ' because it does not exist locally')
		if options.download:
			album_path = create_dir(root, album_title, _entry_ts(album), options, ' because it does not exist on the local albums')
			picasa_photos = get_picasa_photos(client, album)
			for photo_title, photo in picasa_photos.iteritems():
				download_photo(album_path, photo, options, ' because it does not exist on the local album "%s"' % album_title)

def run():
	parser = argparse.ArgumentParser(description = 'Sync one or more directories with your Picasa Web account. If only one directory is given and it doesn\'t contain any supported file, it is assumed to be the parent of all the local albums.')
	parser.add_argument('-n', '--dry-run', dest = 'dry_run', action = 'store_true', help = 'Do everything except creating or deleting albums and photos')
	parser.add_argument('-D', '--debug', dest = 'debug', action = 'store_true', help = 'Debug Picasa API usage')
	parser.add_argument('-v', '--verbose', dest = 'verbose', action = 'count', help = 'Verbose output (can be given more than once)')
	parser.add_argument('-m', '--max-photos', metavar = 'NUMBER', dest = 'max_photos', type = int, default = MAX_PHOTOS_PER_ALBUM, help = 'Maximum number of photos in album (limited to %s)' % MAX_PHOTOS_PER_ALBUM)
	parser.add_argument('-u', '--upload', dest = 'upload', action = 'store_true', help = 'Upload missing remote photos')
	parser.add_argument('-d', '--download', dest = 'download', action = 'store_true', help = 'Download missing local photos')
	parser.add_argument('-r', '--update', dest = 'update', action = 'store_true', help = 'Update changed local or remote photos')
	group = parser.add_argument_group('DANGEROUS', 'Dangerous options that should be used with care')
	group.add_argument('--force-update', dest = 'force_update', action = 'store_true', help = 'Force updating photos regardless of modified status (Assumes --update)')
	group.add_argument('--delete-photos', dest = 'delete_photos', action = 'store_true', help = 'Delete remote or local photos not present on the other album')
	group = parser.add_argument_group('VERY DANGEROUS', 'Very dangerous options that should be used with extreme care')
	group.add_argument('--delete-albums', dest = 'delete_albums', action = 'store_true', help = 'Delete remote or local albums not present on the other system')
	parser.add_argument('path', metavar = 'PATH', nargs = '+', help = 'Parent directory of the albums to sync')
	options = parser.parse_args()

	if options.verbose == 1:
		log_level = logging.INFO
	elif options.verbose >= 2:
		log_level = logging.DEBUG
	else:
		log_level = logging.WARNING

	logging.basicConfig(level = log_level)

	if options.max_photos > MAX_PHOTOS_PER_ALBUM:
		LOG.warn('Maximum number of photos in album is bigger than the Picasa limit (%s), using this number as limit' % MAX_PHOTOS_PER_ALBUM)
		options.max_photos = MAX_PHOTOS_PER_ALBUM

	if not options.upload and not options.download:
		LOG.info('No upload or download specified. Using bidirectional sync.')
		options.upload = True
		options.download = True

	if (options.delete_photos or options.delete_albums) and options.upload and options.download:
		LOG.warn('You cannot delete when using bidirectional syncing. Disabling deletion.')
		options.delete_photos = False
		options.delete_albums = False

	if options.force_update and options.upload and options.download:
		LOG.warn('You cannot force update when using bidirectional syncing. Disabling forced updates.')
		options.force_update = False

	if options.force_update and not options.update:
		options.update = True

	if len(options.path) > 1 and (options.download or options.delete_albums):
		LOG.warn('You cannot download or delete albums when using more than one directories. Disabling download and/or album deletion.')
		options.download = False
		options.delete_albums = False

	if len(options.path) == 1:
		options.path = options.path[0]

	sync(options, options.path)

def main():
	try:
		run()
	except KeyboardInterrupt:
		pass

if __name__ == '__main__':
		main()

