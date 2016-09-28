import celery
from django.db import models
from django.db.models.signals import post_save
from django.urls import reverse
from django.dispatch import receiver
from django.contrib.postgres.fields import JSONField

from model_utils.models import TimeStampedModel
from model_utils.fields import StatusField, MonitorField
from model_utils import Choices

from packtools import utils as packtools_utils


PACKAGE_VIRUSSCAN_STATUS_QUEUED = 'queued'
PACKAGE_VIRUSSCAN_STATUS_UNDETERMINED = 'undetermined'
PACKAGE_VIRUSSCAN_STATUS_INFECTED = 'infected'
PACKAGE_VIRUSSCAN_STATUS_UNINFECTED = 'uninfected'

XMLMEMBER_SPS_STATUS_VALID = 'valid'
XMLMEMBER_SPS_STATUS_INVALID = 'invalid'


class Deposit(TimeStampedModel):
    """O depósito de um pacote SciELO PS para ingresso na coleção.

    A mudança de estados do pacote -- esperando análise, aceito e rejeitado --
    é implementada pela instância de ``StatusField``, uma máquina de estados
    finitos extremamente simplificada.

    A superclasse ``TimeStampedModel`` provê os atributos ``created`` e
    ``modified``, contendo a data e hora de criação e de modificação da
    entidade, respectivamente.

    Mais informação sobre ``StatusField`` e ``TimeStampedModel`` em:
    https://django-model-utils.readthedocs.io/en/latest/
    """
    STATUS = Choices('deposited', 'rejected', 'accepted')

    status = StatusField()
    status_changed = MonitorField(monitor='status')
    depositor = models.CharField(max_length=16)


class Package(TimeStampedModel):
    """Pacote depositado para inclusão na coleção.

    Um pacote é basicamente um maço, zipado, de arquivos XML -- que devem ser
    válidos em relação a especificação SciELO PS -- e seus respectivos ativos
    digitais, incluindo PDF.

    Uma instância de ``Package`` contém atributos que representam seu
    status na verificação de vírus. São os atributos cujo identificador
    começa com ``virus_scan_``. Os status possíveis são representados pelas
    variáveis:
      - models.PACKAGE_VIRUSSCAN_STATUS_QUEUED (verificação ainda pendente),
      - models.PACKAGE_VIRUSSCAN_STATUS_UNDETERMINED (quando não foi possível
        verificar o pacote, por exemplo por exceder o tamanho máximo aceito
        pelo antivirus),
      - models.PACKAGE_VIRUSSCAN_STATUS_INFECTED (o pacote está infectado),
      - models.PACKAGE_VIRUSSCAN_STATUS_UNINFECTED (o pacote não está infectado).

    A superclasse ``TimeStampedModel`` provê os atributos ``created`` e
    ``modified``, contendo a data e hora de criação e de modificação da
    entidade, respectivamente.

    Mais informação sobre ``TimeStampedModel`` em:
    https://django-model-utils.readthedocs.io/en/latest/
    """
    deposit = models.OneToOneField(Deposit, on_delete=models.CASCADE,
            related_name='package')
    file = models.FileField(upload_to='packages/%Y/%m/%d/', max_length=1024)
    md5_sum = models.CharField(max_length=32)  # 32 dígitos hexadecimais

    VIRUS_SCAN_STATUS = Choices(
            PACKAGE_VIRUSSCAN_STATUS_QUEUED,
            PACKAGE_VIRUSSCAN_STATUS_UNDETERMINED,
            PACKAGE_VIRUSSCAN_STATUS_INFECTED,
            PACKAGE_VIRUSSCAN_STATUS_UNINFECTED)
    virus_scan_status = StatusField(choices_name='VIRUS_SCAN_STATUS')
    virus_scan_status_changed = MonitorField(monitor='virus_scan_status',
            when=[PACKAGE_VIRUSSCAN_STATUS_UNDETERMINED,
                  PACKAGE_VIRUSSCAN_STATUS_INFECTED,
                  PACKAGE_VIRUSSCAN_STATUS_UNINFECTED])
    virus_scan_details = models.CharField(max_length=2048, default='')


class PackageMember(models.Model):
    """Arquivo membro de ``Package``.
    """
    package = models.ForeignKey(Package, on_delete=models.CASCADE,
            related_name='members')
    name = models.CharField(max_length=1024)


    def open(self):
        """Extrai o membro como um objeto tipo arquivo -- instância de
        ``zipfile.ZipExtFile``.

        Deve ser utilizado preferencialmente com gerenciador de contexto, e.g.:

            with package_member.open() as member_file:
                data = member_file.read()
        """
        with packtools_utils.Xray.fromfile(self.package.file.path) as xpack:
            return xpack.get_file(self.name)

    def __str__(self):
        return self.name

    def is_xml(self):
        return self.name.endswith('.xml')


class XMLMemberControlAttrs(models.Model):
    """Atributos de controle para ``PackageMember`` do tipo XML.
    """
    member = models.OneToOneField(PackageMember, on_delete=models.CASCADE,
            related_name='xml_control_attrs')

    SPS_CHECK_STATUS = Choices(
            XMLMEMBER_SPS_STATUS_VALID,
            XMLMEMBER_SPS_STATUS_INVALID)
    sps_check_status = StatusField(choices_name='SPS_CHECK_STATUS')
    sps_check_status_changed = MonitorField(monitor='sps_check_status')
    sps_check_details = JSONField()


@receiver(post_save, sender=Package)
def create_package_members(sender, instance, created, **kwargs):
    """Cria as entidades de representam cada arquivo membro de ``Package``.
    """
    if created:
        celery.current_app.send_task(
                'frontdesk.tasks.create_package_members',
                args=[instance.pk])


@receiver(post_save, sender=Package)
def scan_package_for_viruses(sender, instance, created, **kwargs):
    """Varre o arquivo referenciado por ``Package.file`` em busca de vírus.
    """
    if created:
        celery.current_app.send_task(
                'frontdesk.tasks.scan_package_for_viruses',
                args=[instance.pk])


@receiver(post_save, sender=PackageMember)
def validate_package_member_against_sps(sender, instance, created, **kwargs):
    """Valida XMLs contra a SciELO PS.
    """
    if created and instance.is_xml():
        celery.current_app.send_task(
                'frontdesk.tasks.validate_package_member',
                args=[instance.pk])

