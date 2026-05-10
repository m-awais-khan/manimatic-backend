# Generated for Manimatic Visual Animation Playground integration

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0010_remove_scene_manifest_remove_scene_source_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='scene',
            name='manifest',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='scene',
            name='source',
            field=models.CharField(
                choices=[
                    ('chat', 'Chat'),
                    ('dataset', 'Dataset'),
                    ('playground', 'Playground'),
                ],
                default='chat',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='PlaygroundProject',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(default='Untitled Playground', max_length=255)),
                ('graph_data', models.JSONField(blank=True, default=dict)),
                ('manifest', models.JSONField(blank=True, null=True)),
                ('compiled_python', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_scene', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='playground_projects', to='api.scene')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='playground_projects', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
    ]
