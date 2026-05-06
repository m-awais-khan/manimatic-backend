from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('auth/google/', views.GoogleAuthView.as_view(), name='google_auth'),
    path('auth/profile/', views.UserProfileView.as_view(), name='user_profile'),
    path('auth/wipe/', views.WipeDataView.as_view(), name='wipe_data'),
    path('auth/training-consent/', views.DataTrainingConsentView.as_view(), name='training_consent'),
    
    # Chats
    path('chats/', views.ChatListView.as_view(), name='chat_list'),
    path('chats/<uuid:pk>/', views.ChatDetailView.as_view(), name='chat_detail'),
    
    # Scenes
    path('scenes/', views.GenerateSceneView.as_view(), name='generate_scene'),
    path('scenes/from-dataset/', views.DatasetSceneView.as_view(), name='dataset_scene'),
    path('scenes/<uuid:pk>/', views.SceneStatusView.as_view(), name='scene_status'),
    
    # Dataset suggestions (no auth required)
    path('suggestions/', views.DatasetSuggestionsView.as_view(), name='dataset_suggestions'),
    
    # Stitcher
    path('stitch/', views.StitchVideosView.as_view(), name='stitch_videos'),
    path('stitched/', views.StitchedVideoListView.as_view(), name='stitched_list'),
    path('stitched/<uuid:pk>/', views.StitchedVideoDetailView.as_view(), name='stitched_detail'),

    # Temporary debug endpoint — verify S3 config on Render
    path('debug/s3/', views.S3DebugView.as_view(), name='s3_debug'),

    # Prompt Enhancement (RAG + Groq → Gemini fallback)
    path('enhance-prompt/', views.PromptEnhanceView.as_view(), name='enhance_prompt'),


]
