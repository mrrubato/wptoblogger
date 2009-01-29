#!/usr/bin/env python

#    Copyright (c) 2007 Michael Porter
#
#    Permission is hereby granted, free of charge, to any person obtaining a copy
#    of this software and associated documentation files (the "Software"), to deal
#    in the Software without restriction, including without limitation the rights
#    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#    copies of the Software, and to permit persons to whom the Software is
#    furnished to do so, subject to the following conditions:
#
#    The above copyright notice and this permission notice shall be included in
#    all copies or substantial portions of the Software.
#
#    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#    THE SOFTWARE.
import gdata
import time

"""
    Utility to copy blog posts from Wordpress to Blogger.

    Typical usage:

     1. Use the Wordpress export feature to export your blog as an XML file
     2. Run:
        python wptoblogger.py -u <BLOGGER_USER> -b <BLOG_ID> -a <POST_AUTHOR> <WORDPRESS_XML_FILE>
        (add -d switch to delete *all* your blogger posts first)

    Note that (at the time of writing) Blogger has a limit on the number of
    posts per day so you may have problems if you have a lot to transfer.

    Requires the following Python libraries:

       BeautifulSoup - http://www.crummy.com/software/BeautifulSoup/  
       Google's GData Python Client - http://code.google.com/p/gdata-python-client/  

"""

import logging
logger = logging.getLogger("wptoblogger")

## WORDPRESS UTILS #############################################

def get_posts(wp_xml_file):
    "Extract posts (with comments) from a WordPress XML export file"
    doc = wp_xml_file.read()
    # Ensure UTF8 chars get through correctly by ensuring we have a
    # compliant UTF8 input doc
    doc = doc.decode('utf-8', 'replace').encode('utf-8')
    import BeautifulSoup
    feed = BeautifulSoup.BeautifulSoup(doc)
    for entry in feed('item'):
        # Only include published posts
        if (entry.find('wp:post_type').string == 'post') and (entry.find('wp:status').string == 'publish'):
            comments = []
            for comment in entry('wp:comment'): 
                approved = comment.find('wp:comment_approved') 
                # Only include approved comments
                if approved and (approved.string == '1'):
                    comments.append(dict(
                        content = comment.find('wp:comment_content').string,
                        author = comment.find('wp:comment_author').string, 
                        author_url = comment.find('wp:comment_author_url').string, 
                        published = _wp_date_to_time(comment.find('wp:comment_date_gmt').string)
                    ))
            yield dict(
                id = entry.find('wp:post_id').string,
                title = entry.find('title').string,
                content = entry.find('content:encoded').string,
                author = entry.find('dc:creator').string,
                published = _wp_date_to_time(entry.find('wp:post_date_gmt').string),
                categories = [c.string for c in entry('category')],
                comments = comments
            )

def _wp_date_to_time(wp_date):
    import time
    return time.strptime(wp_date, '%Y-%m-%d %H:%M:%S')


## BLOGGER UTILS ###############################################

def get_service(user, pw):
    from gdata import service
    svc = service.GDataService(user, pw)
    svc.source="codesimple-wptoblogger-1.0"
    svc.service="blogger"
    svc.server="www.blogger.com"
    svc.ProgrammaticLogin()
    return svc

def get_authsub_url(next_url):
    from gdata import service
    scope = 'http://www.blogger.com/feeds'
    secure = False
    session = True
    blogger_service = service.GDataService()
    return blogger_service.GenerateAuthSubURL(next_url, scope, secure, session)

def get_service_from_token(authsub_token):
    from gdata import service
    svc = service.GDataService()
    svc.auth_token = authsub_token
    svc.UpgradeToSessionToken()
    return svc

def comment_post_url_from_post(post):
    link = [l for l in post.link if l.rel=="replies" and l.type=="application/atom+xml"][0]
    return link.href

def to_blog_time(time_tuple):
    import time
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time_tuple)

def call_post(svc, entry, url):
    tries = 5
    while True:
        try:
            tries -= 1
            result = svc.Post(entry, url)
            break
        except gdata.service.RequestError, e:
            logger.error("Failed to post to %s, will retry %d times. Error was %s" % (url, tries, e))
            if tries < 1:
                raise
            time.sleep(1)
    return result

def blogger_post(svc, blog_id, author, title, content, published_date, categories):
    import gdata, functools
    from gdata import atom
    entry = gdata.GDataEntry()
    entry.author.append(atom.Author(atom.Name(text=author)))
    entry.title = atom.Title('xhtml', title)
    entry.content = atom.Content(content_type='html', text=content)
    entry.published = atom.Published(to_blog_time(published_date))
    entry.category.extend([atom.Category(c, 'http://www.blogger.com/atom/ns#') for c in categories])
    # Note that this appears to return a valid response even if your post has not been 
    # uploaded due to Blogger limits on posts-per-day 
    post = call_post(svc, entry, '/feeds/%s/posts/default' % blog_id)
    return dict(
        post = post,
        svc=svc,
        url=comment_post_url_from_post(post)
    )

def comment(svc, url, author, author_url, content, published_date, add_author = False):
    import gdata
    from gdata import atom
    add_author = True
    entry = gdata.GDataEntry()
    entry.author.append(atom.Author(atom.Name(text=author))) # according to forum and practice this is ignored :(
    if add_author:
        author_html = author
        if author_url:
            author_html = '<a href="%s">' % author_url + author_html + '</a>'
        content = '<em>Comment from %s:</em>\r\n\r\n' % author_html + content
    entry.content = atom.Content(content_type='xhtml', text=content)
    entry.published = atom.Published(to_blog_time(published_date))
    return call_post(svc, entry, url)
        

def blogger_get_posts(svc, blog_id):
    feed = svc.GetFeed('/feeds/%s/posts/default' % blog_id)
    return feed.entry

def delete_posts(svc, posts):
    for post in posts:
       svc.Delete(post.GetEditLink().href) 

def clear_blog(svc, blog_id):
    delete_posts(svc, blogger_get_posts(svc, blog_id))


## MAIN ########################################################

def convert(wp_xml_file, blogger_service, blog_id, post_author):
    posts = get_posts(wp_xml_file)
    for post in posts:
        logger.info("Processing post %s" % post['title'])
        posted = blogger_post(blogger_service, blog_id, post_author, post['title'], post['content'], post['published'], post['categories'])
        for com in post['comments']:
            author = com['author']
            comment(posted['svc'], posted['url'], author, com['author_url'], 
                        com['content'], com['published'], 
                        add_author = (author != post_author),
                        ) 

def run(wp_xml_file, blogger_user, blogger_password, authsub_token, blog_id, post_author, delete):
    if authsub_token:
        blogger_service = get_service_from_token(authsub_token)
    else:
        blogger_service = get_service(blogger_user, blogger_password)
    if delete:
        logger.info("Removing existing posts from blog %s" % blog_id)
        clear_blog(blogger_service, blog_id)
    convert(wp_xml_file, blogger_service, blog_id, post_author)

def main():
    from optparse import OptionParser
    parser = OptionParser(usage='usage: %prog [OPTION...] FILE', description='Extract posts from WordPress XML export file FILE and post to specified blogger blog.')
    parser.set_defaults(delete=False)
    parser.add_option("-u", "--user", dest="blogger_user",
                      help="Blogger username", metavar="USERNAME")
    parser.add_option("-p", "--password", dest="blogger_password",
                      help="Blogger password (omit option to get prompted)", metavar="PASSWORD")
    parser.add_option("-t", "--token", dest="authsub_token",
                      help="Blogger AuthSub token (instead of username/password)", metavar="TOKEN")
    parser.add_option("-b", "--blog", dest="blog_id",
                      help="Blogger blog ID", metavar="ID")
    parser.add_option("-a", "--author", dest="post_author",
                      help="Author for Blogger posts", metavar="NAME")
    parser.add_option("-d", "--delete", action="store_true", dest="delete",
                      help="Delete all entries from existing blog first")
    (options, args) = parser.parse_args()

    if not options.authsub_token and not options.blogger_password:
        import getpass
        options.blogger_password = getpass.getpass('Blogger password: ')

    if not (((options.blogger_user and options.blogger_password) or options.authsub_token) and options.blog_id and options.post_author):
        parser.error("Must specify blogger user/password or token and blog ID and post author.")
            
    if len(args) >= 1:
        file = open(args[0], 'r')
    else:
        import sys
        file = sys.stdin

    import logging
    logging.basicConfig(level=logging.INFO)

    run(wp_xml_file=file, **options.__dict__)


if __name__ == "__main__":
    main()

