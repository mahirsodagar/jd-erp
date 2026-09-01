# Institute moves off Campus and onto Program, matching legacy
# `program_master.inst_id`. A campus is institute-agnostic again and can
# host programs from several institutes at once.
#
# Operation order matters: Program.institute is added and backfilled from
# the existing Campus.institute values BEFORE that column is dropped.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_program_institute(apps, schema_editor):
    """Give each Program the institute its campuses pointed at.

    A program is only backfilled when its campuses agree on exactly one
    non-null institute. Programs whose campuses disagree, or have none,
    are left null and printed for manual resolution — guessing here
    would silently misfile students under the wrong legal entity.
    """
    Program = apps.get_model("master", "Program")

    resolved = 0
    ambiguous, orphaned = [], []

    for program in Program.objects.prefetch_related("campuses").all():
        institute_ids = {
            c.institute_id
            for c in program.campuses.all()
            if c.institute_id is not None
        }
        if len(institute_ids) == 1:
            program.institute_id = institute_ids.pop()
            program.save(update_fields=["institute"])
            resolved += 1
        elif len(institute_ids) > 1:
            ambiguous.append((program.code, sorted(institute_ids)))
        else:
            orphaned.append(program.code)

    print(f"\n  master.0014: backfilled institute on {resolved} program(s).")
    if ambiguous:
        print(
            f"  master.0014: {len(ambiguous)} program(s) span MULTIPLE "
            f"institutes — left null, set them by hand:"
        )
        for code, ids in ambiguous:
            print(f"    - {code}: institute ids {ids}")
    if orphaned:
        print(
            f"  master.0014: {len(orphaned)} program(s) had no campus with "
            f"an institute — left null: {', '.join(orphaned)}"
        )


def unbackfill_program_institute(apps, schema_editor):
    """Reverse: push the program's institute back onto its campuses.

    Lossy by nature — a campus that hosted two institutes' programs can
    only keep one. Last program wins, which is why the forward direction
    refuses to guess.
    """
    Program = apps.get_model("master", "Program")
    for program in Program.objects.prefetch_related("campuses").all():
        if program.institute_id:
            program.campuses.all().update(institute_id=program.institute_id)


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0006_employee_employment_category'),
        ('master', '0013_alter_program_category'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. New institute link on Program.
        migrations.AddField(
            model_name='program',
            name='institute',
            field=models.ForeignKey(blank=True, help_text='Owning institute (legacy `program_master.inst_id`). Nullable only for legacy rows that could not be backfilled — set it on every new program.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='programs', to='master.institute'),
        ),

        # 2. Carry the data across while Campus.institute still exists.
        migrations.RunPython(
            backfill_program_institute,
            unbackfill_program_institute,
        ),

        # 3. Only now is it safe to drop the old column.
        migrations.RemoveField(
            model_name='campus',
            name='institute',
        ),

        # 4. Remaining legacy fields restored from the PHP schema.
        migrations.AddField(
            model_name='course',
            name='semester',
            field=models.ForeignKey(blank=True, help_text='Semester this course sits in (legacy `course_master.sem_id`).', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='courses', to='master.semester'),
        ),
        migrations.AddField(
            model_name='program',
            name='degree',
            field=models.ForeignKey(blank=True, help_text='Legacy `program_master.degree_id`.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='programs', to='master.degree'),
        ),
        migrations.AlterField(
            model_name='program',
            name='degree_type',
            field=models.CharField(blank=True, help_text='Free-text degree label, e.g. B.Des, M.Des, Diploma. Kept alongside `degree` because notifications.sender routes the outgoing mail domain off this string (is_diploma()) — do not drop it.', max_length=40),
        ),
        migrations.CreateModel(
            name='CurriculumMapping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='curriculum_created', to=settings.AUTH_USER_MODEL)),
                ('instructor', models.ForeignKey(blank=True, help_text='Legacy `instur_id`. Null = curriculum row only.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='curriculum', to='employees.employee')),
                ('program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='curriculum', to='master.program')),
                ('semester', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='curriculum', to='master.semester')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='curriculum', to='master.subject')),
            ],
            options={
                'verbose_name': 'Curriculum mapping',
                'verbose_name_plural': 'Curriculum mappings',
                'ordering': ('program', 'semester__number', 'subject__name'),
                'indexes': [models.Index(fields=['program', 'semester'], name='master_curr_program_4824fd_idx'), models.Index(fields=['instructor', 'program'], name='master_curr_instruc_9323b3_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('instructor__isnull', False)), fields=('program', 'semester', 'subject', 'instructor'), name='uniq_curriculum_prog_sem_sub_instr'), models.UniqueConstraint(condition=models.Q(('instructor__isnull', True)), fields=('program', 'semester', 'subject'), name='uniq_curriculum_prog_sem_sub_noinstr')],
            },
        ),
    ]
