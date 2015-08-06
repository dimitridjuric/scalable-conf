#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime, timedelta
import json
import os
import time
import logging
import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote
from operator import lt, gt
from google.appengine.api import urlfetch
from google.appengine.ext import ndb
from google.appengine.api import memcache
from google.appengine.api import taskqueue
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import TeeShirtSize
from models import ConflictException
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import Session
from models import SessionFormIn, SessionFormOut
from models import SessionForms
from models import SessionTypeForm
from models import SessionSpeakerForm
from models import SessionQueryForm
from models import DoubleSessionQueryForm
from models import SpeakersForm
from models import StringMessage
from models import BooleanMessage
from models import ConflictException
from models import Speaker, SpeakerForm
from utils import getUserId
from settings import WEB_CLIENT_ID





EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

SESSION_DEFAULTS = {
    "session_type": "Presentation",
    "location": "default location",
    "date": None
}

OPERATORS = {
        'EQ':   '=',
        'GT':   '>',
        'GTEQ': '>=',
        'LT':   '<',
        'LTEQ': '<=',
        'NE':   '!='
        }

FIELDS =    {
        'CITY': 'city',
        'TOPIC': 'topics',
        'MONTH': 'month',
        'MAX_ATTENDEES': 'maxAttendees',
        }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESS_POST_REQUEST = endpoints.ResourceContainer(
    SessionFormIn,
    websafeConferenceKey=messages.StringField(1),
)

SESS_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_TYPE_QUERY = endpoints.ResourceContainer(
    SessionTypeForm,
    websafeKey=messages.StringField(1)
)

SPEAKER_QUERY_CONTAINER = endpoints.ResourceContainer(
    speaker=messages.StringField(1)
)

WISHLIST_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionKey=messages.StringField(1),
)

SPEAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speakerKey=messages.StringField(1),
)

MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT ANNOUNCEMENTS"

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

@endpoints.api( name='conference',
                version='v1',
                allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
                scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(
                data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)
    
    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))
    
    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)
    
    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"],
                                                   filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

    
# - - - Registration - - - - - - - - - - - - - - - - - - - -
    
    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)
    
    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)
    
    
    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser()  # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf,
                                    names[conf.organizerUserId]) for conf in conferences])
    
    
# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        # create a new key of kind Profile from the id
        p_key = ndb.Key(Profile, user_id)
        # get the entity from datastore by using get() on the key
        profile = p_key.get()
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            # save the profile to datastore
            profile.put()
        return profile      # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
        # put the modified profile to the datastore
            prof.put()
        # return ProfileForm
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    # TODO 1
    # 1. change request class
    # 2. pass request to _doProfile function
    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        # TODO 1
        # return an existing announcement from Memcache or an empty string.
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or ""
        return StringMessage(data=announcement)

# - - - Sessions - - - - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionFormOut."""
        sf = SessionFormOut()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                # convert Date to date string; just copy others
                if field.name in ['start_time', 'date']:
                    setattr(sf, field.name, str(getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
        setattr(sf, 'sessionKey', session.key.urlsafe())
        setattr(sf, 'speaker', self._getSpeakerNames(session.key.urlsafe()))
        sf.check_initialized()
        return sf

    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""
        
        # get user profile and check if user is authorized
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        
        # get conference object
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        
        # check user is conference creator
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can create a session for this conference.')
        
        # check required fields
        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")
        if (not request.start_time) or (not request.date):
            raise endpoints.BadRequestException(
                "Session 'date' and 'start_time' fields required")
        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeConferenceKey']

        # add default values for those missing (both data model & outbound Message)
        for df in SESSION_DEFAULTS:
            if data[df] in (None, []):
                data[df] = SESSION_DEFAULTS[df]
                setattr(request, df, SESSION_DEFAULTS[df])

        # convert time to integer, date to datetime
        if data['start_time']:
            data['start_time'] = int(data['start_time'])
        if data['date']:
            data['date'] = datetime.strptime(data['date'], "%Y-%m-%d").date()
        
        # convert duration to integer
        if data['duration']:
            data['duration'] = int(data['duration'])
            
        # check session time is valid (during the conference)
        if data['date']:
            if data['date'] < conf.startDate or data['date'] > conf.endDate:
                raise endpoints.BadRequestException(
                    'The session time is outside the dates of the conference.'
                )
        
        # generate Session Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        c_key = conf.key
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        s_key = ndb.Key(Session, s_id, parent=c_key)
        data['key'] = s_key

        # create Conference & return (modified) ConferenceForm
        session = Session(**data)
        session.put()
        # check if speaker is featured speaker to queue
        taskqueue.add(params={'sk': request.speakerKeys, 'name': request.name,
                              'wsck': request.websafeConferenceKey},
                      url='/tasks/is_speaker_featured')
        return self._copySessionToForm(session)

    
    @endpoints.method(SESS_POST_REQUEST, SessionFormOut, path='session/add',
            http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session in conference."""
        
        return self._createSessionObject(request)
    
    @endpoints.method(CONF_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/sessions',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        
        # get Conference object from request
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        
        # get the sessions for this conference
        sessions = Session.query(ancestor=conf.key).order(Session.date,
                                                          Session.start_time)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions])
    
    @endpoints.method(SESSION_TYPE_QUERY, SessionForms,
            path='conference/{websafeKey}/sessionstype',
            http_method='POST',
            name='getConferenceSessionByType')
    def getConferenceSessionByType(self, request):
        """Query for session by type for a conferences."""
        
        # all session for the conference filtered by sessionType
        all_sessions = Session.query(
            ancestor=ndb.Key(urlsafe=request.websafeKey))
        sessions = all_sessions.filter(
            Session.session_type == request.session_type)

        return SessionForms(
                items=[self._copySessionToForm(session) for session in
                       sessions])
    
    @endpoints.method(SessionSpeakerForm, SessionForms,
            path='sessionsspeaker',
            http_method='POST',
            name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Query for session by speaker across all conferences."""
        all_sessions = Session.query()
        sessions = all_sessions.filter(
            Session.speakerKeys == request.speakerKey)

        return SessionForms(
                items=[self._copySessionToForm(session) for session in
                       sessions]
                )

# - - - Wishlists - - - - - - - - - - - - - - - - - - - -

    def _wishlistAddition(self, request, addition=True):
        """Add or remove session from user wishlist"""
        
        retval = None  # return value
        prof = self._getProfileFromUser()  # get user Profile

        # get session; check that it exists
        sk = request.sessionKey
        session = ndb.Key(urlsafe=request.sessionKey).get()
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % sk)
        
        # add to wishlist
        if addition:
            # check if session is already in wishlist
            if hasattr(prof, 'sessionWishlistKeys') and \
                    sk in prof.sessionWishlistKeys:
                raise ConflictException(
                    "This session is already in the wishlist")
        
            # add session to wishlist
            prof.sessionWishlistKeys.append(sk)
            retval = True

        # remove from wishlist
        else:
            # check if session is in wishlist
            if hasattr(prof, 'sessionWishlistKeys') and \
                    sk in prof.sessionWishlistKeys:
                # remove session from wishlist
                prof.sessionWishlistKeys.remove(sk)
                retval = True
            else:
                # retval is false if session wasn't in wishlist
                retval = False

        # write things back to the datastore & return
        prof.put()
        return BooleanMessage(data=retval)

    @endpoints.method(WISHLIST_GET_REQUEST, BooleanMessage,
            path='wishlist/add/{sessionKey}',
            http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add a session to the user's wishlist."""
        return self._wishlistAddition(request)
    
    @endpoints.method(WISHLIST_GET_REQUEST, BooleanMessage,
            path='wishlist/remove/{sessionKey}',
            http_method='DELETE', name='removeSessionFromWishlist')
    def removeSessionFromWishlist(self, request):
        """Remove a session from the user's wishlist."""
        return self._wishlistAddition(request, addition=False)

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='sessions/wishlist',
            http_method='GET', name='getSessionsInWishlist')
    def getSessionInWishlist(self, request):
        """Return sessions in wishlist."""

        prof = self._getProfileFromUser()  # get user Profile
        # test if session wishlist exists
        if hasattr(prof, 'sessionWishlistKeys'):
            session_keys = [ndb.Key(urlsafe=sk) for sk in prof.sessionWishlistKeys]
            sessions = ndb.get_multi(session_keys)
        else:
            sessions = []
        # return set of SessionForm objects per session
        return SessionForms(items=[self._copySessionToForm(session)
                                   for session in sessions]
                            )

# - - - Additional Queries - - - - - - - - - - - - - - - - - - - -

    @endpoints.method(SessionQueryForm, SessionForms,
                      path='querySessions',
                      http_method='POST',
                      name='querySessions')
    def querySessions(self, request):
        """Query for sessions of a conference."""
        
        # check required fields
        if not(request.field or request.operator or request.value):
            raise endpoints.BadRequestException(
                "field, operator and value fields required")
        
        # convert date to a datetime object, duration and start_time to int
        if request.field == 'date':
            value = datetime.strptime(request.value, "%Y-%m-%d")
        elif request.field in ['start_time', 'duration']:
            value = int(request.value)
        else:
            value = request.value
            
        # if the request contains a websafeConferenceKey we query the sessions
        # for this conference
        if request.websafeConferenceKey:
            ck = ndb.Key(urlsafe=request.websafeConferenceKey)
            q = Session.query(ancestor=ck)
            sessions = q.filter(ndb.query.FilterNode(request.field,
                                                     request.operator,
                                                     value))

        # if the request doesn't contain a websafeConferenceKey we query the
        # sessions for all the conferences the user is registered for
        else:
            prof = self._getProfileFromUser()
            conferenceKeys = prof.conferenceKeysToAttend
            sessions = []
            # query for each of the conferences to attend
            for k in conferenceKeys:
                q = Session.query(ancestor=ndb.Key(urlsafe=k))
                sessions += q.filter(ndb.query.FilterNode(request.field,
                                                          request.operator,
                                                          value))
        # return individual SessionForm object per Conference
        return SessionForms(
                items=[self._copySessionToForm(session) for session in sessions]
                )

    @endpoints.method(DoubleSessionQueryForm, SessionForms,
                      path='doubleQuerySessions',
                      http_method='POST',
                      name='doubleQuerySessions')
    def doubleQuerySessions(self, request):
        """Double query for sessions of a conference. Allows inequalities on
        two different properties"""
        
        # check required fields
        if not(request.field1 or request.operator1 or request.value1 or
               request.field2 or request.operator2 or request.value2):
            raise endpoints.BadRequestException(
                "field, operator and value fields required")
        
        # convert date and start_time to datetime objects
        if request.field1 == 'date':
            value1 = datetime.strptime(request.value1, "%Y-%m-%d")
            value1d = value1.date()
        elif request.field1 in ['start_time', 'duration']:
            value1 = int(request.value1)
            value1d = value1
        else:
            value1 = request.value1
            value1d = value1
        if request.field2 == 'date':
            value2 = datetime.strptime(request.value2, "%Y-%m-%d")
            value2d = value2.date()
        elif request.field2 in ['start_time', 'duration']:
            value2 = int(request.value2)
            value2d = value2
        else:
            value2 = request.value2
            value2d = value2
            
        # get conference key, and the sessions for that conference
        ck = ndb.Key(urlsafe=request.websafeConferenceKey)
        q = Session.query(ancestor=ck)
        # apply the first query
        q1 = q.filter(ndb.query.FilterNode(request.field1,
                                           request.operator1,
                                           value1))
        
        # if we have two inequalities in the query, the second is done in memory
        if request.operator1 != '=' and request.operator2 != '=':
            sessions = []
            # do the comparisons in memory
            if request.operator2 == '<':
                for e in q1:
                    if getattr(e, request.field2) < value2d:
                        sessions.append(e)
            if request.operator2 == '>':
                for e in q1:
                    if getattr(e, request.field2) > value2d:
                        sessions.append(e)
        
        # if we don't have two inequalities the second query is done by ndb
        else:
            sessions = q1.filter(ndb.query.FilterNode(request.field2,
                                                      request.operator2,
                                                      value2))
        # return individual SessionForm object per Conference
        return SessionForms(
                items=[self._copySessionToForm(session) for session in sessions]
                )

    @staticmethod
    def _getSpeakerKeys(wsck):
        """get speaker keys for all sessions of a conference"""
        # get Conference object from request
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)
        
        # get the speakers for this conference
        sessions = Session.query(ancestor=conf.key).fetch(projection=[Session.speakerKeys])
        # flattening the list of list of speakers
        speakers = [speaker for session in sessions for speaker in session.speakerKeys]
        return speakers

    @endpoints.method(CONF_GET_REQUEST, SpeakersForm,
            path='conference/{websafeConferenceKey}/speakers',
            http_method='GET', name='getConferenceSpeakers')
    def getConferenceSpeakers(self, request):
        """Return a list of speakers for all sessions of a conference
        (by websafeConferenceKey)."""
        
        speakerKeys = self._getSpeakerKeys(request.websafeConferenceKey)
        speakers = [self._getSpeakerName(sk) for sk in speakerKeys]
        # copy the list to a form
        form = SpeakersForm(speaker=speakers)
        form.check_initialized()
        return form

    @endpoints.method(CONF_GET_REQUEST, StringMessage,
            path='conference/{websafeConferenceKey}/featuredSpeaker',
            http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Returns the featured speaker stored in memcache"""
        speaker, sessionName = memcache.get('featuredSpeaker') or ('','')
        # copy the list to a form
        form = StringMessage(data=speaker+' - '+sessionName)
        form.check_initialized()
        return form

# - - - Speaker Objects - - - - - - - - - - - - - - - - - - - -

    def _getSpeakerNames(self, sessionKey):
        """Returns a list of names of the speakers for a session"""
        session = ndb.Key(urlsafe=sessionKey).get()
        speakerKeys = session.speakerKeys
        names = [self._getSpeakerName(sk) for sk in speakerKeys]
        return names

    @staticmethod
    def _getSpeakerName(speakerKey):
        """Returns the name of a speaker from the websafe speaker key"""
        speaker = ndb.Key(urlsafe=speakerKey).get()
        return speaker.name

    def _copySpeakerToForm(self, speaker):
        """Copy fields from Speaker to SpeakerForm."""
        sf = SpeakerForm()
        for field in sf.all_fields():
            if hasattr(speaker, field.name):
                setattr(sf, field.name, getattr(speaker, field.name))
            elif field.name == "speakerKey":
                setattr(sf, field.name, speaker.key.urlsafe())
        sf.check_initialized()
        return sf

    def _createSpeakerObject(self, request):
        """Create or update a Speaker object, returning SpeakerForm/request.
        In this version, any user can create a speaker, this allows speakers
        to be reused for different conferences"""
        
        # check for required field
        if not request.name:
            raise endpoints.BadRequestException("Speaker 'name' field required")

        # create Speaker & return SpeakerForm
        speaker = Speaker(name=request.name, organisation=request.organisation)
        speaker.put()
        return self._copySpeakerToForm(speaker)

    @endpoints.method(SpeakerForm, SpeakerForm, path='speaker',
            http_method='POST', name='createSpeaker')
    def createSpeaker(self, request):
        """Create new speaker"""
        return self._createSpeakerObject(request)

    @endpoints.method(SPEAKER_GET_REQUEST, SpeakerForm,
            path='speaker/{speakerKey}',
            http_method='GET', name='getSpeaker')
    def getSpeaker(self, request):
        """Return requested speaker (by websafe speaker key)."""
        # get speaker object from request; bail if not found
        speaker = ndb.Key(urlsafe=request.speakerKey).get()
        if not speaker:
            raise endpoints.NotFoundException(
                'No speaker found with key: %s' % request.speakerKey)
        # return SpeakerForm
        return self._copySpeakerToForm(speaker)
    
# registers API
api = endpoints.api_server([ConferenceApi]) 
