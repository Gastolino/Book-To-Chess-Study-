# Your private library on Cloudflare

## This setup is optional

The app on GitHub Pages (<https://gastolino.github.io/Book-To-Chess-Study-/>)
already keeps a library: each device's browser keeps the books you add on
it, with the program's reading, your corrections and your place, and opens
them again without reading them. A book moves to another device as one file
("Save to Files", then "Add a book" on the other device); the README's
"Using the app" says how. Nothing below is needed for that.

The Cloudflare site adds one thing: a single library for all your devices,
which they share without files. If its setup does not work for you, leave it:
the GitHub Pages app goes on working, and the Cloudflare workflow does
nothing while the two secrets of step 6 are missing (delete them to stop
it). The workflow stops by itself after 25 minutes at most and never waits
for an answer, so a run that cannot finish ends with a red cross and a
message in its log.

## What the Cloudflare site does

The Cloudflare site is the same app with a library kept by the site: the
program reads each book once, and the site keeps the book, the program's
reading of it, your corrections and the page you last read. Every device you
sign in on (iPhone, iPad, Mac) then opens the book at once, at your page,
without reading it again.

The site is private. Cloudflare Access lets in only your email address, and
the files are kept in a storage bucket that has no public address. The site
uses Cloudflare's free plans: Pages (the site), R2 (the files), D1 (the
records) and Zero Trust (the sign-in). Cloudflare's pricing pages list the
free allowances of each; one person's library of books stays far inside them.

The setup takes about half an hour, once. The steps below use the names the
program expects; type them exactly as written.

| What | Name |
|---|---|
| The site (Pages project) | `chess-book-reader` |
| The storage bucket (R2) | `chessbook-books` |
| The database (D1) | `chessbook` |

## 1. Create a Cloudflare account

Go to <https://dash.cloudflare.com/sign-up>, sign up with your email address
and confirm it. You need no domain name of your own: the site lives at
`chess-book-reader.pages.dev`.

## 2. Turn on R2 and create the bucket

1. In the dashboard, open **R2 Object Storage** in the menu on the left.
2. Cloudflare asks you to turn R2 on and to give a payment method (a card).
   It asks this even for the free use of R2; you are charged only if the use
   goes beyond the free allowance.
3. Choose **Create bucket**, type the name `chessbook-books`, leave the
   location on **Automatic** and choose **Create bucket**.

Leave the bucket private: do not turn on its public access or connect a
domain to it.

## 3. Create the database

1. In the menu on the left, open **Storage & Databases** and then **D1 SQL
   Database** (in some versions of the dashboard it sits under **Workers &
   Pages**).
2. Choose **Create**, type the name `chessbook` and choose **Create**.

The program creates the tables inside it by itself.

## 4. Note your account ID

Open **Workers & Pages** in the menu. The **Account ID** shows on the right
of that page (or on the account's home page). Copy it into a note; step 6
needs it.

## 5. Create an API token for GitHub

GitHub publishes the site with this token.

1. Open your profile (the person icon at the top right) and choose **My
   Profile**, then **API Tokens**, then **Create Token**.
2. At the bottom, next to **Create Custom Token**, choose **Get started**.
3. Name the token `GitHub chess books`.
4. Under **Permissions**, add three lines (choose **+ Add more** for each new
   line):
   - **Account**, **Cloudflare Pages**, **Edit**
   - **Account**, **D1**, **Edit**
   - **Account**, **Workers R2 Storage**, **Edit**
5. Under **Account Resources**, choose **Include** and your account.
6. Choose **Continue to summary**, then **Create Token**.
7. Copy the token that shows. Cloudflare shows it only once.

## 6. Give GitHub the two secrets

1. Open the repository on GitHub, then **Settings**, then **Secrets and
   variables**, then **Actions**.
2. On the **Secrets** tab, choose **New repository secret** twice:
   - Name `CLOUDFLARE_API_TOKEN`, and as the secret the token of step 5.
   - Name `CLOUDFLARE_ACCOUNT_ID`, and as the secret the account ID of step 4.

## 7. Publish the site

On GitHub, open **Actions**, choose **Publish the library on Cloudflare** in
the list on the left, then **Run workflow** and **Run workflow** again. The
run takes a few minutes. From now on every change to `main` publishes the
site again by itself.

The first run creates the Pages project `chess-book-reader` (and the bucket
and the database too, if steps 2 and 3 were skipped). Until the two secrets
exist, the run does nothing and still ends with a green tick.

If the run stops with a red cross and mentions a permission or
"Authentication error", check the three permissions of step 5.

## 8. Let in only your email address (Cloudflare Access)

Do this before you add a book.

1. In the dashboard, open **Zero Trust**. The first time, Cloudflare asks
   for a team name (any short name, such as your surname) and a plan: choose
   the **Free** plan.
2. In Zero Trust, open **Access**, then **Applications**, then **Add an
   application**, and choose **Self-hosted**.
3. Name it `Chess books`. Under the application's domain, type
   `chess-book-reader.pages.dev`. Add a second domain (**+ Add domain**) with
   `*.chess-book-reader.pages.dev`, so that the trial copies Cloudflare keeps
   of each publication are protected as well.
4. Add a policy: name it `Only me`, action **Allow**, and under **Include**
   choose **Emails** and type your email address.
5. Keep the sign-in method **One-time PIN** (Cloudflare emails you a code),
   and save the application.

Then give the site two more details, so that it checks every sign-in itself:

6. Open the application you just made: its overview shows the **Application
   Audience (AUD) Tag**, a long string of letters and digits. Copy it.
7. In Zero Trust, open **Settings**, then **Custom Pages** (or **Team domain**):
   the team domain reads `yourteam.cloudflareaccess.com`. Copy it.
8. On GitHub, open **Settings**, **Secrets and variables**, **Actions**, and
   this time the **Variables** tab. Choose **New repository variable** twice:
   - Name `ACCESS_TEAM_DOMAIN`, value the team domain (such as
     `yourteam.cloudflareaccess.com`).
   - Name `ACCESS_AUD`, value the audience tag.
9. Run the workflow again as in step 7.

## 9. Open your library

Open <https://chess-book-reader.pages.dev>. Cloudflare asks for your email
address and sends you a code; after it the page shows **Your library**.
Choose **Add a book** and pick a chess book PDF. The program uploads it,
reads it (one to five minutes; you can read while it reads) and keeps the
reading. Any other device opens the book from the library in seconds.

On an iPhone or an iPad, open the address in Safari, choose the share button
and **Add to Home Screen**, so that the library opens like an app.

## What the site keeps, and where

- In the bucket `chessbook-books`, in a folder named after your email
  address: each book's PDF, the program's reading of it (compressed) and a
  small picture of its first page.
- In the database `chessbook`: each book's title, page count, size, the date
  it was added and last opened, the page and move you last read, your
  corrections, your bookmarks and your selection of pages and diagrams.

**Remove** in the library deletes the book and everything kept for it.

A change to the program makes the stored readings out of date: the next time
a book opens, the program reads it again (with your corrections) and keeps
the new reading. Your corrections, selection and place are kept as they are.

## For a programmer: running the site on one computer

```
npm install
python3 tools/build_web.py --out site --pymupdf WHEEL --chess WHEEL
npx wrangler d1 execute DB --local --file server/schema.sql
npx wrangler pages dev site --binding DEV_USER=you@example.com
```

`wrangler pages dev` keeps local copies of the bucket and the database in
`.wrangler/`. `DEV_USER` stands in for Cloudflare Access; it must never be
set on the Cloudflare site. `tests/test_library.py` runs the server and the
whole library this way.
