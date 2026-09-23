import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_user_phone_number'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Transaction',
        ),
        migrations.DeleteModel(
            name='Referral',
        ),
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('tx_type', models.CharField(max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=18)),
                ('status', models.CharField(default='COMPLETED', max_length=10)),
                ('reference', models.UUIDField(default=uuid.uuid4)),
                ('related_id', models.UUIDField(blank=True, null=True)),
                ('description', models.TextField(default='')),
                ('date', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Referral',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('reward', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('date', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('referred', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='referred_by_ref', to=settings.AUTH_USER_MODEL)),
                ('referrer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='referrals_made', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Deposit',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=18)),
                ('wallet_type', models.CharField(default='USDT', max_length=50)),
                ('tx_hash', models.CharField(blank=True, default='', max_length=150)),
                ('status', models.CharField(default='PENDING', max_length=10)),
                ('date_requested', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('date_resolved', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='deposits', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('action', models.CharField(max_length=150)),
                ('detail', models.CharField(blank=True, default='', max_length=255)),
                ('date', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('admin', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='support',
            name='status',
            field=models.CharField(default='UNREAD', max_length=10),
        ),
        migrations.AlterField(
            model_name='withdrawal',
            name='amount',
            field=models.DecimalField(decimal_places=2, max_digits=18),
        ),
    ]