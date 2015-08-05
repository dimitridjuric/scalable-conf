#!/usr/bin/env python
import webapp2
import logging
from google.appengine.api import app_identity
from google.appengine.api import mail
from google.appengine.api import memcache
from conference import ConferenceApi


class SetAnnouncementHandler(webapp2.RequestHandler):
    def get(self):
        """Set Announcement in Memcache."""
        ConferenceApi._cacheAnnouncement()


class SendConfirmationEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )


class IsSpeakerFeaturedHandler(webapp2.RequestHandler):
    def post(self):
        """Check if speaker should be featured speaker and if so update the
        featuredSpeaker in memcache"""
        # check if any speaker appear in more than one session for this conference
        conferenceSpeakers = ConferenceApi._getSpeakers(self.request.get('wsck'))
        speakers = self.request.get_all('speaker')
        for speaker in speakers:
            if conferenceSpeakers.count(speaker) > 1:
                memcache.set('featuredSpeaker', (speaker, self.request.get('name')))

logging.getLogger().setLevel(logging.DEBUG)

app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
    ('/tasks/is_speaker_featured', IsSpeakerFeaturedHandler)
], debug=True)
