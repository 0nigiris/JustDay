---
name: kindle
description: Find an ebook and send it to the user's Kindle ("закинь на Kindle книгу …") — legal sources only; purchases are done by the user.
---

# Send a book to Kindle

1. Identify the exact book (title, author, language the user wants).
2. Find a legal copy:
   - Public domain / free: Project Gutenberg (`https://www.gutenberg.org/ebooks/search/?query=`), Standard Ebooks, Wikisource, author/publisher free pages, open-access (arXiv, OAPEN).
   - Russian classics: public-domain texts on Wikisource or legal libraries.
   - Not free → find the official store page (Amazon Kindle Store, Litres, publisher) and give the user the link: "Книга платная, открыл страницу покупки." Opening it in the browser is fine; buying is the user's action. Never use pirate sites (Flibusta, LibGen, Z-Library, Anna's Archive etc.).
3. Get the file: EPUB preferred (Kindle accepts EPUB, PDF, DOCX, TXT). Download to `~/Downloads/Books/`. If the user bought it, look for the new file in `~/Downloads` (`fd --changed-within 1h . ~/Downloads`).
4. Deliver (Send to Kindle):
   - Via browser: `https://www.amazon.com/sendtokindle` in claude-in-chrome → upload with `file_upload` → confirm. Requires the user to be logged in to Amazon.
   - Or via email (Gmail connector, if it supports attachments): to the user's Send-to-Kindle address from memory/profile; the sender must be approved in Amazon settings. Sending requires the user's yes.
5. Report: "Отправил на Киндл, появится через пару минут."
Remember the user's Kindle email address (it is not a secret) once they tell you.
