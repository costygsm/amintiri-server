# Amintiri

A lightweight photo server for **Synology NAS**, with an Android app: Google Photos–style backup,
memories and sharing for your family, while your pictures stay plain files in your own `Photos` folder.

<p align="center">
  <img src="docs/screenshots/timeline.jpg" alt="Timeline with “On this day” memories" width="100%">
</p>

## What it does

**Backup from the phone**
- Automatic backup of the folders you choose, in the background and as soon as you take a photo;
  on Wi-Fi only or on mobile data too, optionally only while charging.
- **Fast at home:** on your home Wi-Fi the phone uploads straight to the NAS, not through the internet
  and Cloudflare — on our network 1 → 8 MB/s, see [Backup at home](#backup-at-home).
- **You know it works:** a notification if photos haven't been backed up for over a day, with the likely
  reason; the screen can stay on during a big first backup and dims itself to a quiet progress view.
- Free up space: delete from the phone what is already safe on the NAS.

**Browsing**
- Timeline by day / month / year, with a year scrubber on the web.
- **Memories:** "on this day" from past years at the top, full-screen stories on the phone and a
  morning notification.
- **Places** from the photos' GPS, worked out offline on the NAS; **search** for "summer 2024",
  "August", a city or an album name.
- Favourites, rotate (your original file is never rewritten), **archive** (hide photos from the
  timeline and memories; they stay in albums and search), 30-day trash.

**Sharing**
- **Shared family albums:** share an album with other NAS accounts; everyone sees it and adds their own
  photos, while the rest of each person's library stays private.
- Public links for an album, for people without an account; turn them off any time.

**Your NAS, your rules**
- Sign in with your **DSM accounts** (2-step verification supported). No second user database.
- Photos are saved to `homes/<user>/Photos/<year>/<month>/`, named by the date they were taken.
  Stop using Amintiri tomorrow and nothing is locked in.
- **Light:** one small container (Python + SQLite); runs fine on ARM models.
- Android app with fingerprint lock, and a web app in any browser.

## Screenshots

| | | |
|---|---|---|
| <img src="docs/screenshots/albums.jpg" alt="Albums"> | <img src="docs/screenshots/shared-album.jpg" alt="A shared album"> | <img src="docs/screenshots/share.jpg" alt="Sharing an album with another account"> |
| **Albums**, with Archive and shared albums | A **shared album**: everyone adds their own photos | **Share** with the people on your NAS |
| <img src="docs/screenshots/places.jpg" alt="Places"> | <img src="docs/screenshots/search.jpg" alt="Search for “summer 2026”"> | <img src="docs/screenshots/select.jpg" alt="Multi-select"> |
| **Places**, from the photos' GPS — offline | **Search**: “summer 2026”, “August”, a city | Select many: album, archive, download, delete |
| <img src="docs/screenshots/viewer.jpg" alt="Viewer"> | <img src="docs/screenshots/timeline-dark.jpg" alt="Dark theme"> | |
| Viewer: rotate, archive, add to an album | Follows the system's dark theme | |

<p align="center">
  <img src="docs/screenshots/phone-memory.jpg" alt="A memory in the Android app: 2 years ago" width="19%">
  <img src="docs/screenshots/phone-upload.jpg" alt="The quiet upload screen in the Android app" width="19%">
  <img src="docs/screenshots/phone-timeline.jpg" alt="On a phone" width="19%">
  <img src="docs/screenshots/phone-timeline-dark.jpg" alt="On a phone, dark theme" width="19%">
  <img src="docs/screenshots/phone-places.jpg" alt="Places on a phone" width="19%">
</p>
<p align="center"><sub>Android app: a memory and the quiet upload screen. The others: the web app on a phone.</sub></p>

<sub>Sample photos from <a href="https://unsplash.com">Unsplash</a> via <a href="https://picsum.photos">Lorem Picsum</a>; the memory is the author's own.</sub>

> The interface is in **Romanian and English** (follows the phone or browser; can be changed in Settings).

## Requirements

- Synology DSM 7 with **Container Manager**
- **User Home service** on (Control Panel → User & Group → Advanced → Enable user home service)
- Each person needs **DSM: Allow** (Control Panel → User & Group → the user → Applications)
- A domain name with HTTPS (DSM reverse proxy + certificate; Cloudflare works)

## Install

1. In File Station create a folder, e.g. `/docker/amintiri`, and **inside it a folder named `data`**
   (Container Manager does not create missing folders: without `data` the container won't start —
   *Bind mount failed: … does not exist*).
2. Container Manager → **Project → Create** → path: that folder → *Create docker-compose.yml* →
   paste [`docker-compose.yml`](docker-compose.yml) → adjust `TZ` if needed → **Done**.
3. Control Panel → Login Portal → Advanced → **Reverse Proxy → Create**:
   HTTPS `photos.example.com` 443 → HTTP `localhost` **8090**.
4. Open `https://photos.example.com` in a browser and sign in with your DSM account.
5. Install the **Android app** from the [Releases](../../releases) page (`amintiri-*.apk`),
   enter `photos.example.com` as the server and sign in.

Updating: Container Manager → Project → amintiri → **Action → Build** (pulls the latest image),
or `docker compose pull && docker compose up -d`.

### Firewall

If the DSM firewall blocks by country and you use Cloudflare, allow the
[Cloudflare IP ranges](https://www.cloudflare.com/ips-v4) on ports 80/443 above the deny rule —
otherwise some visitors get error 522.

## Backup at home

Away from home the phone uploads through your domain (`https://photos.example.com`). At home that same
path goes out to the internet and back — through Cloudflare, if you use it — which caps uploads at
roughly the speed of your internet upload, often 1 MB/s.

With `POZE_HOST: 0.0.0.0` (the default in [`docker-compose.yml`](docker-compose.yml)) the app notices it
is on the same Wi-Fi as the NAS and sends photos **directly to the NAS's local address**
(`http://192.168.x.x:8090`). On our network that took a phone from about 1 MB/s to 8 MB/s; the first
backup of a full phone goes from days to hours. Nothing to set up in the app: it decides on its own,
before every backup, and falls back to the domain as soon as you leave home.

How it stays safe:

- **The phone checks it's really your NAS** before sending the sign-in token to a local address: the NAS
  must answer a one-time challenge with a key only it and your account know. A different device that
  happens to have the same address on another Wi-Fi gets nothing.
- **The local port answers only devices on your network** (private addresses: 192.168.x.x, 10.x.x.x,
  172.16–31.x.x) and only the app's API; the web pages stay on the HTTPS domain.
- The DSM firewall must allow your home network on port **8090** (e.g. *Allow — 192.168.0.0/24 — all ports*).
  **Do not forward port 8090 on your router.**

To turn it off, set `POZE_HOST: 127.0.0.1`; everything then goes through the domain, as before.

## How it works

- Sign-in is checked against DSM (`SYNO.API.Auth` on `127.0.0.1:5000`); the server never stores passwords.
- The server indexes each user's `Photos` folder (photos and videos already there show up too),
  makes thumbnails and keeps albums, favourites and the trash in `data/poze.db`.
- A copy of the database is written every day to `data/backup/` (last 7 kept).
- Uploads are resumable (8 MB chunks) and de-duplicated by SHA-256.
- Rotation is stored in the database and applied to thumbnails; downloads give you the original file.
- Shared albums only reference photos: each photo stays in its owner's folder, and leaving an album
  takes your photos out of it.

## Data and privacy

Everything stays on your NAS. The app talks only to your server and, to check for app updates,
to GitHub. There is no analytics and no account with us.

## Licence

Copyright © 2026 BACIU I CONSTANTIN II ([servicegsm.eu](https://servicegsm.eu)).
Contact: office@servicegsm.eu

The server is released under the **GNU AGPL-3.0** ([LICENSE](LICENSE)).
The Android app is distributed as a signed APK on the Releases page; its source is not published.
